import path from "node:path"
import { tool } from "@opencode-ai/plugin"

export default tool({
  description:
    "Probe Tang's OpenCode source/current-session contract without returning IDs, paths, titles, transcript text, tool values, or credentials.",
  args: {
    expectedProvider: tool.schema
      .enum(["openai", "xai"])
      .describe("Exact provider ID expected for this acceptance run"),
  },
  async execute(args, context) {
    const script = path.join(
      context.worktree,
      "scripts",
      "probe_opencode_contract.py",
    )
    const executable = process.env.TANG_OPENCODE_EXECUTABLE ?? "opencode"
    try {
      const processResult = Bun.spawn(
        [
          "python3",
          script,
          "--opencode",
          executable,
          "--cwd",
          context.directory,
          "--current-session-id",
          context.sessionID,
          "--current-message-id",
          context.messageID,
          "--expect-provider",
          args.expectedProvider,
          "--expected-version",
          "1.17.20",
          "--overall-timeout",
          "120",
        ],
        {
          cwd: context.directory,
          env: process.env,
          stderr: "ignore",
          stdout: "pipe",
        },
      )
      const terminate = () => {
        try {
          processResult.kill()
        } catch {
          // The process may have exited between the signal and this callback.
        }
      }
      const abort = () => terminate()
      context.abort.addEventListener("abort", abort, { once: true })
      if (context.abort.aborted) terminate()
      const timeout = setTimeout(terminate, 125_000)
      const [stdout, exitCode] = await Promise.all([
        new Response(processResult.stdout).text(),
        processResult.exited,
      ]).finally(() => {
        clearTimeout(timeout)
        context.abort.removeEventListener("abort", abort)
      })
      if (exitCode !== 0 && stdout.trim().length === 0) {
        return JSON.stringify({
          schema_version: 1,
          result: "fail",
          error_code: "probe_unavailable",
        })
      }
      return stdout.trim()
    } catch {
      return JSON.stringify({
        schema_version: 1,
        result: "fail",
        error_code: "probe_unavailable",
      })
    }
  },
})
