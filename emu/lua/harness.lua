-- S1100FX MAME test harness (loaded with -autoboot_script).
--
-- Runs a step file, one command per line, advancing on emulated frames:
--   wait <frames>                 let the machine run
--   press <port> <field> [frames] hold a front-panel key, e.g. press KEY3 MIDI
--                                 (<field> matches the start of the key name)
--   snap <name>                   write the LCD as <out>/<name>.lcd
--                                 ('#' = pixel on, '.' = off, one row per line)
--   mem <name> <addr> <len>       write CPU memory as <out>/<name>.bin
--   exit                          stop MAME
-- Paths come from the environment: S1100FX_STEPS, S1100FX_OUT.
-- Everything the harness does is logged to <out>/harness.log.

local steps_path = os.getenv("S1100FX_STEPS")
local out = os.getenv("S1100FX_OUT") or "."
local machine = manager.machine
local log = io.open(out .. "/harness.log", "w")

local function say(fmt, ...)
    log:write(string.format("[%6d] " .. fmt .. "\n", machine.screens[":screen"]:frame_number(), ...))
    log:flush()
end

local steps = {}
for line in io.lines(steps_path) do
    line = line:gsub("#.*", ""):match("^%s*(.-)%s*$")
    if line ~= "" then
        local words = {}
        for w in line:gmatch("%S+") do words[#words + 1] = w end
        steps[#steps + 1] = words
    end
end

local function find_field(port_name, prefix)
    local port = machine.ioport.ports[":" .. port_name]
    if not port then error("no input port " .. port_name) end
    for name, field in pairs(port.fields) do
        if name:sub(1, #prefix) == prefix then return field, name end
    end
    error("no key starting with '" .. prefix .. "' in " .. port_name)
end

local function snap(name)
    local screen = machine.screens[":screen"]
    local pixels, w, h = screen:pixels()
    local f = io.open(out .. "/" .. name .. ".lcd", "w")
    for y = 0, h - 1 do
        local row = {}
        for x = 0, w - 1 do
            local i = (y * w + x) * 4 + 1
            -- ARGB little-endian: bytes B,G,R,A; lit LCD pixels are bright
            local b, g, r = pixels:byte(i, i + 2)
            row[#row + 1] = (r + g + b >= 384) and "#" or "."
        end
        f:write(table.concat(row), "\n")
    end
    f:close()
end

local pc, wait_until, held = 1, 0, nil

local function frame()
    local now = machine.screens[":screen"]:frame_number()
    if now < wait_until then return end
    if held then
        held:clear_value()
        held = nil
    end
    while pc <= #steps do
        local s = steps[pc]
        pc = pc + 1
        local cmd = s[1]
        if cmd == "wait" then
            wait_until = now + tonumber(s[2])
            return
        elseif cmd == "press" then
            local field, name = find_field(s[2], s[3])
            field:set_value(1)
            held = field
            say("press %s", name)
            wait_until = now + tonumber(s[4] or "6")
            return
        elseif cmd == "snap" then
            snap(s[2])
            say("snap %s", s[2])
        elseif cmd == "mem" then
            local space = machine.devices[":maincpu"].spaces["program"]
            local addr, len = tonumber(s[3]), tonumber(s[4])
            local f = io.open(out .. "/" .. s[2] .. ".bin", "wb")
            for a = addr, addr + len - 1 do f:write(string.char(space:read_u8(a))) end
            f:close()
            say("mem %s 0x%x %d", s[2], addr, len)
        elseif cmd == "exit" then
            say("exit")
            machine:exit()
            return
        else
            error("unknown step: " .. cmd)
        end
    end
end

subscription = emu.add_machine_frame_notifier(frame)
say("harness loaded: %d steps", #steps)
