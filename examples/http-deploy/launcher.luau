--!nocheck
-- HTTP-deploy launcher for tinyvm.
--
-- Fetches the combined macro-VM + user-program AST over HTTP, decodes
-- the JSON response, and runs the user program through the micro-VM.
-- The launcher needs four things, in addition to the micro-VM itself:
--
--   * ./jsondec        - a JSON decoder
--   * ./httpget        - a `function(url) -> body_string` HTTP-GET shim
--   * ./config         - the URL to fetch
--   * the micro-VM     - ./tinyvm
--
-- On Roblox `httpget` is one line:
--   return function(url) return game:GetService("HttpService"):GetAsync(url) end
-- In this example's standalone test the driver pre-fetches the URL and
-- writes a shim that returns the bytes directly -- because standalone
-- `luau` has no network stack. The launcher's code is identical.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")
local httpGet  = require("./httpget")
local config   = require("./config")

local body      = httpGet(config.payloadUrl)
local inputData = decode(body)

hostInfo = {
    appName       = "tinyvm-http-deploy-example",
    serverInfo    = config.serverInfo or "unknown",
    fetchedUrl    = config.payloadUrl,
    payloadBytes  = #body,
}

local ok, err = pcall(micro, inputData, getfenv())
if not ok then
    print("user program raised: " .. tostring(err))
end
