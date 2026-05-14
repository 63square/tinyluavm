--!nocheck
-- Split-deploy launcher for tinyvm.
--
-- Loads three Luau modules:
--   1. ./tinyvm        -- the micro-VM (a function)
--   2. ./macrovm-ast   -- the pre-decoded macro-VM AST  (returns {K, F})
--   3. ./user-ast      -- the pre-decoded user program  (returns {K, F})
--
-- Combines (2) and (3) into the `inputData` table the micro-VM expects
-- and hands it the caller's environment via `getfenv()`. The macro-VM
-- resolves both stdlib globals and any host-injected values through
-- the same env.
--
-- In a real Roblox project the three modules would live anywhere -- in
-- this example they're laid out flat next to this file so plain
-- `require("./...")` works.
local micro   = require("./tinyvm")
local mvmAst  = require("./macrovm-ast")  -- returns {K, F}
local userAst = require("./user-ast")     -- returns {K, F}

-- Anything written to `getfenv()` becomes visible to the user program
-- as a global. Things on `_G` are visible through fallthrough.
hostInfo = {
    appName    = "tinyvm-split-deploy-example",
    appVersion = "1.0",
}

local ok, err = pcall(micro, {m = mvmAst, u = userAst}, getfenv())
if not ok then
    print("user program raised: " .. tostring(err))
end
