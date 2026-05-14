--!nocheck
-- HTTP-deploy launcher for tinyvm.
--
-- Fetches the combined macro-VM + user-program AST over HTTP, decodes
-- the JSON response, and runs it through the micro-VM. The whole data
-- plane lives on the server; nothing about the user program is
-- baked into the deployed Luau source.
--
-- The launcher needs four things, in addition to the micro-VM itself:
--
--   * ./jsondec        - a JSON decoder (we ship one alongside)
--   * ./httpget        - a `function(url) -> body_string` HTTP-GET shim
--   * ./config         - the URL to fetch (so the launcher is generic)
--   * the micro-VM     - ./tinyvm
--
-- On Roblox you'd implement `httpget` as
--   return function(url) return game:GetService("HttpService"):GetAsync(url) end
-- In this example's standalone test, the driver pre-fetches the URL
-- and writes a shim that returns the bytes directly -- because
-- standalone `luau` has no network stack. The launcher's code is
-- identical in both cases.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")
local httpGet  = require("./httpget")
local config   = require("./config")

print(`== launcher: GET {config.payloadUrl} ==`)
local body = httpGet(config.payloadUrl)
print(`fetched {#body} bytes; decoding...`)

local inputData = decode(body)

local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv
userEnv.hostInfo = {
    appName       = "tinyvm-http-deploy-example",
    serverInfo    = config.serverInfo or "unknown",
    fetchedUrl    = config.payloadUrl,
    payloadBytes  = #body,
}

print("== launcher: starting user program ==")
local ok, err = pcall(micro, inputData, userEnv, "user.luau")
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
