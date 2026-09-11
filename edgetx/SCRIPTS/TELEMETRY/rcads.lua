-- RCADS gun-radio control. EdgeTX 128x64 (MT12).
-- Four fields on CRSF FM 0x21: MODE,READY,RISK,TAKEOVER
-- Copy to /SCRIPTS/TELEMETRY/rcads.lua
-- ENTER = demo. This script does not drive the car.

local MODE = { [0] = "MAN", "ASST", "L3" }
local TIMEOUT = 150
local DEAD = 18
local DEMOS = {
  { 0, 1, 0, 0 },
  { 1, 1, 12, 0 },
  { 2, 1, 23, 5 },
  { 2, 0, 80, 0 },
  { 2, 1, 40, 2 }
}

local last
local last_t
local src = "SA"
local had = false
local prev_to = 0
local demo = 0
local view

local function clamp(v, a, b)
  if v < a then return a end
  if v > b then return b end
  return v
end

local function has(name)
  return getFieldInfo(name) ~= nil
end

local function num(name)
  local v = getValue(name)
  if type(v) ~= "number" then return nil end
  return v
end

local function ch_pct(name)
  return math.floor((num(name) or 0) / 10.24)
end

local function req_mode()
  local sa = num("sa") or 0
  if sa > 512 then return 2 end
  if sa < -512 then return 0 end
  return 1
end

local function rssi_ok()
  local rssi = num("1RSS") or num("RSSI")
  if rssi and rssi ~= 0 then return true end
  local lq = num("RQly")
  return (lq ~= nil and lq > 0)
end

local function parse_fm(s)
  if type(s) ~= "string" then return nil end
  s = string.upper((string.gsub(s, " ", "")))
  local a, b, c, d = string.match(s, "^(MAN|ASST|L3),(%d+),(%d+),(%d+)")
  if not a then
    a = string.match(s, "^(MAN|ASST|L3)$")
  end
  local md
  if a == "L3" then md = 2
  elseif a == "ASST" then md = 1
  elseif a == "MAN" then md = 0
  else return nil end
  return {
    md = md,
    rd = b and clamp(tonumber(b) or 0, 0, 1) or 0,
    rk = c and clamp(tonumber(c) or 0, 0, 100) or 0,
    to = d and clamp(tonumber(d) or 0, 0, 30) or 0
  }
end

local function accept(rep, from, now)
  last = rep
  last_t = now
  src = from
  had = true
end

local function ingest(now)
  if demo > 0 then
    local d = DEMOS[demo]
    accept({ md = d[1], rd = d[2], rk = d[3], to = d[4] }, "DEM", now)
    return
  end
  if has("ADmd") then
    accept({
      md = clamp(math.floor(num("ADmd") or 0), 0, 2),
      rd = has("ADrd") and clamp(math.floor(num("ADrd") or 0), 0, 1) or 0,
      rk = has("ADrk") and clamp(math.floor(num("ADrk") or 0), 0, 100) or 0,
      to = has("ADto") and clamp(math.floor(num("ADto") or 0), 0, 30) or 0
    }, "AD", now)
    return
  end
  if has("FM") then
    local p = parse_fm(getValue("FM"))
    if p then
      accept(p, "FM", now)
    end
  end
end

local function phase_of(req, md, rd, to, steer, thr, linked)
  if not linked then return "lost" end
  if to > 0 then return "takeover" end
  if md == 2 and (math.abs(steer) > DEAD or math.abs(thr) > DEAD) then
    return "override"
  end
  if req == 2 and rd == 0 then return "blocked" end
  if md == 2 then return "l3" end
  if md == 1 then return "asst" end
  return "man"
end

local function banner_of(ph, to)
  if ph == "takeover" then return "TOVR " .. to .. "s" end
  if ph == "override" then return "WHEEL" end
  if ph == "blocked" then return "BLOCK" end
  if ph == "lost" then return "LOST" end
  return "HOLD"
end

local function step(now)
  local req = req_mode()
  local steer = ch_pct("ch1")
  local thr = ch_pct("ch2")
  local link = (last_t ~= nil) and ((now - last_t) <= TIMEOUT)

  if had and not link then
    prev_to = 0
    view = {
      req = req, md = 0, rd = 0, rk = 0, to = 0,
      ph = "lost", src = "LOST", alarm = true, beep = false,
      steer = steer, thr = thr
    }
    return
  end

  local md, rd, rk, to, from
  if link and last then
    md, rd, rk, to, from = last.md, last.rd, last.rk, last.to, src
  else
    md, rd, rk, to, from = req, (rssi_ok() and 1 or 0), 0, 0, "SA"
  end

  local ph = phase_of(req, md, rd, to, steer, thr, true)
  local beep = (to > 0 and prev_to == 0)
  prev_to = to
  view = {
    req = req, md = md, rd = rd, rk = rk, to = to,
    ph = ph, src = from,
    alarm = (ph == "takeover" or ph == "override" or ph == "lost" or ph == "blocked"),
    beep = beep, steer = steer, thr = thr
  }
end

local function tick()
  local now = getTime()
  ingest(now)
  step(now)
  if view.beep and playTone then
    playTone(2800, 80, 0, PLAY_NOW)
  end
end

local function bar(x, y, w, h, v)
  lcd.drawRectangle(x, y, w, h)
  local inner = w - 2
  local mid = x + 1 + math.floor(inner / 2)
  lcd.drawLine(mid, y + 1, mid, y + h - 2, SOLID, FORCE)
  local n = math.floor(inner / 2 * clamp(v, -100, 100) / 100)
  if n > 0 then
    lcd.drawFilledRectangle(mid, y + 1, n, h - 2, FORCE)
  elseif n < 0 then
    lcd.drawFilledRectangle(mid + n, y + 1, -n, h - 2, FORCE)
  end
end

local function run(event)
  if event == EVT_VIRTUAL_ENTER then
    demo = (demo + 1) % (#DEMOS + 1)
    if demo == 0 then
      last, last_t, src, had, prev_to = nil, nil, "SA", false, 0
    end
  end
  tick()
  local v = view
  lcd.clear()
  lcd.drawFilledRectangle(0, 0, 128, 10, FORCE)
  lcd.drawText(1, 1, "RCADS", INVERS)
  lcd.drawText(127, 1, MODE[v.md], INVERS + RIGHT + (v.alarm and BLINK or 0))

  lcd.drawText(1, 12, (v.rd == 1) and "READY" or "NOT RDY", SMLSIZE + ((v.rd == 1) and 0 or BLINK))
  local lq = num("RQly")
  if lq then
    lcd.drawText(58, 12, "LQ " .. math.floor(lq), SMLSIZE)
  end
  lcd.drawText(127, 12, v.src, SMLSIZE + RIGHT)

  lcd.drawText(1, 22, "ST", SMLSIZE)
  bar(16, 22, 88, 9, v.steer)
  lcd.drawText(127, 22, v.steer, SMLSIZE + RIGHT)
  lcd.drawText(1, 34, "TH", SMLSIZE)
  bar(16, 34, 88, 9, v.thr)
  lcd.drawText(127, 34, v.thr, SMLSIZE + RIGHT)

  lcd.drawText(1, 46, "RISK " .. v.rk, SMLSIZE)
  local bn = banner_of(v.ph, v.to)
  local bf = SMLSIZE + RIGHT
  if v.ph == "takeover" then bf = bf + BLINK
  elseif v.ph == "override" or v.ph == "blocked" or v.ph == "lost" then bf = bf + INVERS end
  lcd.drawText(127, 46, bn, bf)

  lcd.drawText(1, 56, (demo > 0) and "ENTER=next demo" or "ENTER=demo SA=req", SMLSIZE)
  return 0
end

return { run = run, background = tick }
