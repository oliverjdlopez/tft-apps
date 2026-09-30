/** Run the opt-in bridge integration check using Windows Node from a WSL terminal. */
import { launchFromWsl } from "../wsl.mjs";

launchFromWsl(process.argv.slice(2), new URL("./windows-integration.mjs", import.meta.url)).catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
