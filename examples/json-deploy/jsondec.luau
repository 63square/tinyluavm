--!nocheck
-- Minimal JSON decoder. Returns a single decode() function.
--
-- Supports: objects, arrays, strings, numbers, true, false, null.
-- Maps: JSON null -> Lua nil; JSON object -> Lua table with string keys;
--       JSON array -> Lua array (1-based).
--
-- Not optimized; written for clarity. ~80 lines.

local function decode(s: string)
    local pos = 1

    local function err(msg)
        error(string.format("JSON %s at byte %d near %q", msg, pos,
            string.sub(s, pos, pos + 16)), 2)
    end

    local function skipws()
        while pos <= #s do
            local c = string.byte(s, pos)
            if c == 32 or c == 9 or c == 10 or c == 13 then
                pos += 1
            else
                break
            end
        end
    end

    local parse  -- forward decl

    local function parse_string()
        pos += 1  -- opening "
        local out = {}
        while pos <= #s do
            local ch = string.sub(s, pos, pos)
            if ch == '"' then pos += 1; return table.concat(out) end
            if ch == "\\" then
                pos += 1
                local nxt = string.sub(s, pos, pos)
                pos += 1
                if nxt == "n" then out[#out + 1] = "\n"
                elseif nxt == "r" then out[#out + 1] = "\r"
                elseif nxt == "t" then out[#out + 1] = "\t"
                elseif nxt == "b" then out[#out + 1] = "\b"
                elseif nxt == "f" then out[#out + 1] = "\f"
                elseif nxt == '"' or nxt == "\\" or nxt == "/" then
                    out[#out + 1] = nxt
                elseif nxt == "u" then
                    local hex = string.sub(s, pos, pos + 3); pos += 4
                    local cp = tonumber(hex, 16)
                    if not cp then err("bad \\u escape") end
                    -- Encode the code point as UTF-8.
                    if cp < 128 then
                        out[#out + 1] = string.char(cp)
                    elseif cp < 2048 then
                        out[#out + 1] = string.char(192 + cp // 64,
                                                    128 + cp % 64)
                    else
                        out[#out + 1] = string.char(224 + cp // 4096,
                                                    128 + (cp // 64) % 64,
                                                    128 + cp % 64)
                    end
                else
                    err("bad escape")
                end
            else
                out[#out + 1] = ch
                pos += 1
            end
        end
        err("unterminated string")
    end

    local function parse_object()
        pos += 1  -- {
        local t = {}
        skipws()
        if string.sub(s, pos, pos) == "}" then pos += 1; return t end
        while true do
            skipws()
            if string.sub(s, pos, pos) ~= '"' then err("expected string key") end
            local k = parse_string()
            skipws()
            if string.sub(s, pos, pos) ~= ":" then err("expected :") end
            pos += 1
            t[k] = parse()
            skipws()
            local ch = string.sub(s, pos, pos)
            if ch == "," then pos += 1
            elseif ch == "}" then pos += 1; return t
            else err("expected , or }") end
        end
    end

    local function parse_array()
        pos += 1  -- [
        local t = {}
        skipws()
        if string.sub(s, pos, pos) == "]" then pos += 1; return t end
        local i = 1
        while true do
            t[i] = parse()
            i += 1
            skipws()
            local ch = string.sub(s, pos, pos)
            if ch == "," then pos += 1
            elseif ch == "]" then pos += 1; return t
            else err("expected , or ]") end
        end
    end

    local function parse_number()
        local start = pos
        if string.sub(s, pos, pos) == "-" then pos += 1 end
        while pos <= #s do
            local ch = string.sub(s, pos, pos)
            if (ch >= "0" and ch <= "9")
                    or ch == "." or ch == "e" or ch == "E"
                    or ch == "+" or ch == "-" then
                pos += 1
            else
                break
            end
        end
        local n = tonumber(string.sub(s, start, pos - 1))
        if n == nil then err("bad number") end
        return n
    end

    parse = function()
        skipws()
        local c = string.sub(s, pos, pos)
        if c == '"' then return parse_string() end
        if c == "{" then return parse_object() end
        if c == "[" then return parse_array() end
        if c == "t" then
            if string.sub(s, pos, pos + 3) == "true" then pos += 4; return true end
            err("bad literal")
        end
        if c == "f" then
            if string.sub(s, pos, pos + 4) == "false" then pos += 5; return false end
            err("bad literal")
        end
        if c == "n" then
            if string.sub(s, pos, pos + 3) == "null" then pos += 4; return nil end
            err("bad literal")
        end
        return parse_number()
    end

    return parse()
end

return decode
