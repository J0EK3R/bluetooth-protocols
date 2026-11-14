--[[
XN297L Wireshark dissector (Lua)

Decodes the frames produced by the XN297L sniffer extcap
(../extcap/xn297l_sniffer.py), link type DLT_USER0 (147).

Record layout:
    12 byte pseudo header (see xn297l_sniffer.py)
    on-air bytes starting with the first address byte (MSB-first notation)

What the dissector does:
    * shows the pseudo header (channel, frequency, RSSI, ...)
    * removes the scrambler (if enabled)
    * finds the payload length by checking the CRC (if not known)
    * shows address (TX_ADDR order), payload (FIFO values) and CRC status
    * hands the payload to the dissector table "xn297l.address", keyed by the
      address as upper case hex in TX_ADDR order (e.g. "C1C2C3C4C5"), so that
      device-specific dissectors can be added in separate files:

          local t = DissectorTable.get("xn297l.address")
          t:add("C1C2C3C4C5", my_proto)

Installation: copy this file into the Wireshark personal plugins folder
(Help > About Wireshark > Folders > Personal Lua Plugins).

The bit operations are written with plain arithmetic, so the file works with
both Lua 5.2 (Wireshark <= 4.2) and Lua 5.4 (Wireshark >= 4.4).
--]]

-------------------------------------------------------------------------------
-- Core functions (no Wireshark API, can be unit tested with a plain Lua)
-------------------------------------------------------------------------------

local core = {}

-- XOR of two non-negative integers up to 16 bit
function core.bxor(a, b)
    local result, bit = 0, 1
    while a > 0 or b > 0 do
        local abit, bbit = a % 2, b % 2
        if abit ~= bbit then
            result = result + bit
        end
        a = math.floor(a / 2)        -- math.floor keeps integers in Lua 5.4
        b = math.floor(b / 2)
        bit = bit * 2
    end
    return result
end

-- Reverse the bit order of one byte (0x01 -> 0x80)
function core.rev8(b)
    local r = 0
    for _ = 1, 8 do
        r = r * 2 + (b % 2)
        b = math.floor(b / 2)
    end
    return r
end

-- XN297L scramble sequence (MSB-first bytes, starts with E3 B1 4B EA 85 ...)
-- 7-bit LFSR x^7 + x^4 + 1, initialised to all ones (same as BLE whitening).
function core.scramble_table(length)
    local lfsr = { [0] = 1, 1, 1, 1, 1, 1, 1 }   -- indices 0..6
    local out = {}
    for i = 1, length do
        local byte = 0
        local weight = 1
        for _ = 0, 7 do
            local v3, v6 = lfsr[3], lfsr[6]
            lfsr[3], lfsr[2], lfsr[1], lfsr[0] = lfsr[2], lfsr[1], lfsr[0], lfsr[6]
            lfsr[6], lfsr[5] = lfsr[5], lfsr[4]
            lfsr[4] = (v3 + v6) % 2          -- XOR of two bits
            byte = byte + lfsr[0] * weight   -- collect LSB first
            weight = weight * 2
        end
        out[i] = core.rev8(byte)             -- convert to MSB-first notation
    end
    return out
end

core.SCRAMBLE = core.scramble_table(256)   -- maximum capture: sync + 250 bytes

-- CRC-16/GENIBUS: poly 0x1021, init 0xFFFF, MSB first, final XOR 0xFFFF
-- data: Lua array of bytes, from index first to last (inclusive)
function core.crc16(data, first, last)
    local crc = 0xFFFF
    for i = first, last do
        crc = core.bxor(crc, data[i] * 256)
        for _ = 1, 8 do
            if crc >= 0x8000 then
                crc = core.bxor((crc * 2) % 0x10000, 0x1021)
            else
                crc = (crc * 2) % 0x10000
            end
        end
    end
    return core.bxor(crc, 0xFFFF)
end

-- Descramble a Lua array of on-air bytes (starting at the address)
function core.descramble(raw, scrambled)
    local plain = {}
    for i = 1, #raw do
        if scrambled then
            plain[i] = core.bxor(raw[i], core.SCRAMBLE[i])
        else
            plain[i] = raw[i]
        end
    end
    return plain
end

--[[
Decode one frame.
    raw          Lua array of on-air bytes (address first)
    addr_len     3..5
    payload_len  known payload length or 0 (= search via CRC)
    scrambled    boolean
Returns a table or nil (nil = no length with a valid CRC found):
    plain, payload_len, crc_rx, crc_calc, crc_ok
--]]
function core.decode(raw, addr_len, payload_len, scrambled)
    local plain = core.descramble(raw, scrambled)
    local max_len = #raw - addr_len - 2
    local first, last

    if payload_len > 0 then
        if payload_len > max_len then
            return nil
        end
        first, last = payload_len, payload_len
    else
        first, last = 1, math.min(max_len, 64)
    end

    for plen = first, last do
        local crc_pos = addr_len + plen + 1                 -- 1-based index of CRC high byte
        local crc_rx = plain[crc_pos] * 256 + plain[crc_pos + 1]
        local crc_calc = core.crc16(plain, 1, addr_len + plen)
        if crc_calc == crc_rx or payload_len > 0 then
            return {
                plain = plain,
                payload_len = plen,
                crc_rx = crc_rx,
                crc_calc = crc_calc,
                crc_ok = (crc_calc == crc_rx),
            }
        end
    end
    return nil
end

-------------------------------------------------------------------------------
-- Wireshark part (skipped when loaded outside Wireshark, e.g. by unit tests)
-------------------------------------------------------------------------------

if not Proto then
    XN297L_CORE = core          -- expose the core functions to test scripts
    return
end

local proto = Proto("xn297l", "XN297L 2.4 GHz GFSK frame")

-- Preferences
proto.prefs.search_len = Pref.bool("Find payload length via CRC", true,
    "If the payload length is unknown, try all lengths and use the first one with a valid CRC")

-- Pseudo header fields
local RATE_NAMES = { [0] = "1 Mbps (nRF)", [1] = "2 Mbps (nRF)", [2] = "1 Mbps (BLE)" }

local f = {
    version      = ProtoField.uint8("xn297l.hdr.version", "Header version"),
    flags        = ProtoField.uint8("xn297l.hdr.flags", "Flags", base.HEX),
    flag_scr     = ProtoField.bool("xn297l.hdr.flags.scrambled", "Scrambler on", 8, nil, 0x01),
    flag_prom    = ProtoField.bool("xn297l.hdr.flags.promiscuous", "Promiscuous capture", 8, nil, 0x02),
    flag_raw     = ProtoField.bool("xn297l.hdr.flags.raw", "Raw capture (no XN297L decoding)", 8, nil, 0x04),
    channel      = ProtoField.uint8("xn297l.hdr.channel", "RF channel"),
    freq         = ProtoField.uint16("xn297l.hdr.freq", "Frequency (MHz)"),
    rssi         = ProtoField.int8("xn297l.hdr.rssi", "RSSI (dBm)"),
    addr_len     = ProtoField.uint8("xn297l.hdr.addr_len", "Address length"),
    plen_hint    = ProtoField.uint8("xn297l.hdr.payload_len", "Payload length (configured, 0 = auto)"),
    rate         = ProtoField.uint8("xn297l.hdr.rate", "Data rate", base.DEC, RATE_NAMES),
    timestamp    = ProtoField.uint32("xn297l.hdr.timestamp", "Device timestamp (us)"),

    raw          = ProtoField.bytes("xn297l.raw", "On-air bytes (as received)"),
    sync         = ProtoField.bytes("xn297l.sync", "Sync word (raw capture)"),
    raw_data     = ProtoField.bytes("xn297l.raw_data", "Bytes after the sync word (raw capture)"),
    address_air  = ProtoField.bytes("xn297l.address_air", "Address (on-air, scrambled)"),
    address      = ProtoField.string("xn297l.address", "Address (TX_ADDR order)"),
    payload_len  = ProtoField.uint8("xn297l.payload_len", "Payload length"),
    payload      = ProtoField.bytes("xn297l.payload", "Payload (FIFO values)"),
    crc          = ProtoField.uint16("xn297l.crc", "CRC", base.HEX),
    crc_calc     = ProtoField.uint16("xn297l.crc_calc", "CRC calculated", base.HEX),
    crc_ok       = ProtoField.bool("xn297l.crc_ok", "CRC ok"),
    trailer      = ProtoField.bytes("xn297l.trailer", "Bytes after the frame"),
}
proto.fields = f

local ef_crc_bad = ProtoExpert.new("xn297l.crc_bad", "CRC mismatch",
    expert.group.CHECKSUM, expert.severity.WARN)
local ef_no_crc = ProtoExpert.new("xn297l.no_crc", "No payload length with a valid CRC found",
    expert.group.MALFORMED, expert.severity.NOTE)
proto.experts = { ef_crc_bad, ef_no_crc }

-- Sub dissectors keyed by address (TX_ADDR order, upper case hex)
local addr_table = DissectorTable.new("xn297l.address", "XN297L address", ftypes.STRING, base.NONE, proto)

local HDR_LEN = 12

-- Format an array slice as upper case hex with ':' separators
local function hex(arr, first, last, sep)
    local parts = {}
    for i = first, last do
        parts[#parts + 1] = string.format("%02X", arr[i])
    end
    return table.concat(parts, sep or "")
end

function proto.dissector(tvb, pinfo, tree)
    if tvb:len() < HDR_LEN + 3 then
        return 0
    end

    pinfo.cols.protocol = "XN297L"

    -- --- Pseudo header ------------------------------------------------------
    local flags      = tvb(1, 1):uint()
    local channel    = tvb(2, 1):uint()
    local addr_len   = tvb(4, 1):uint()
    local plen_hint  = tvb(5, 1):uint()
    local scrambled  = (flags % 2) == 1
    local is_raw     = (math.floor(flags / 4) % 2) == 1

    local root = tree:add(proto, tvb(), "XN297L")
    local hdr = root:add(tvb(0, HDR_LEN), "Sniffer header")
    hdr:add(f.version, tvb(0, 1))
    local fl = hdr:add(f.flags, tvb(1, 1))
    fl:add(f.flag_scr, tvb(1, 1))
    fl:add(f.flag_prom, tvb(1, 1))
    fl:add(f.flag_raw, tvb(1, 1))
    hdr:add(f.channel, tvb(2, 1))
    hdr:add(f.freq, tvb(2, 1), 2400 + channel)
    hdr:add(f.rssi, tvb(3, 1))
    hdr:add(f.addr_len, tvb(4, 1))
    hdr:add(f.plen_hint, tvb(5, 1))
    hdr:add(f.rate, tvb(6, 1))
    hdr:add_le(f.timestamp, tvb(8, 4))

    -- --- Frame ----------------------------------------------------------------
    local frame = tvb(HDR_LEN)
    local raw = {}
    for i = 0, frame:len() - 1 do
        raw[i + 1] = frame(i, 1):uint()
    end
    root:add(f.raw, frame)

    -- Raw capture (any sync word, unknown transmitter): show the bytes, no decoding
    if is_raw then
        pinfo.cols.protocol = "RAW 2.4G"
        local sync_len = math.min(addr_len, frame:len())
        root:add(f.sync, frame(0, sync_len))
        if frame:len() > sync_len then
            root:add(f.raw_data, frame(sync_len))
        end
        pinfo.cols.info = string.format("%d MHz  raw  %s | %s", 2400 + channel,
            hex(raw, 1, sync_len, " "), hex(raw, sync_len + 1, #raw, " "))
        return tvb:len()
    end

    if addr_len < 3 or addr_len > 5 or #raw < addr_len + 3 then
        return tvb:len()
    end

    local plen = plen_hint
    if plen == 0 and not proto.prefs.search_len then
        plen = #raw - addr_len - 2          -- assume the whole capture is payload
    end

    local res = core.decode(raw, addr_len, plen, scrambled)

    -- Address (always shown, even without a valid CRC)
    local plain_addr = core.descramble(raw, scrambled)
    local addr_tx = {}
    for i = 1, addr_len do
        addr_tx[i] = plain_addr[addr_len - i + 1]   -- on-air order is reversed TX_ADDR
    end
    local addr_str = hex(addr_tx, 1, addr_len)
    root:add(f.address_air, frame(0, addr_len))
    root:add(f.address, frame(0, addr_len), hex(addr_tx, 1, addr_len, ":"))

    if res == nil then
        root:add_proto_expert_info(ef_no_crc)
        pinfo.cols.info = string.format("%d MHz  addr %s  no valid CRC",
            2400 + channel, hex(addr_tx, 1, addr_len, ":"))
        return tvb:len()
    end

    -- Payload: bit-reverse every byte to get the values written to the FIFO
    local p = res.payload_len
    local payload = ByteArray.new()
    payload:set_size(p)
    for i = 0, p - 1 do
        payload:set_index(i, core.rev8(res.plain[addr_len + i + 1]))
    end
    local payload_tvb = payload:tvb("XN297L payload")

    root:add(f.payload_len, frame(addr_len, p), p)
    root:add(f.payload, frame(addr_len, p), payload:raw())   -- FT_BYTES expects a Lua string
    local crc_item = root:add(f.crc, frame(addr_len + p, 2), res.crc_rx)
    root:add(f.crc_calc, frame(addr_len + p, 2), res.crc_calc):set_generated()
    root:add(f.crc_ok, frame(addr_len + p, 2), res.crc_ok):set_generated()
    if not res.crc_ok then
        crc_item:add_proto_expert_info(ef_crc_bad)
    end
    if #raw > addr_len + p + 2 then
        root:add(f.trailer, frame(addr_len + p + 2))
    end

    pinfo.cols.info = string.format("%d MHz  addr %s  len %d  %s  %s",
        2400 + channel, hex(addr_tx, 1, addr_len, ":"), p,
        res.crc_ok and "CRC ok" or "CRC BAD", payload:tohex(false, " "))

    -- Hand the payload to a device-specific dissector, if one is registered
    addr_table:try(addr_str, payload_tvb, pinfo, tree)

    return tvb:len()
end

-- Register for DLT_USER0 (Wireshark 4.x: wtap_encaps, older: wtap)
local encap = (wtap_encaps and wtap_encaps.USER0) or wtap.USER0
DissectorTable.get("wtap_encap"):add(encap, proto)
