import path from "node:path"
import { tool } from "@opencode-ai/plugin"

export default tool({
  description:
    "Probe Tang's OpenCode source/current-session contract without returning IDs, paths, titles, transcript text, tool values, or credentials.",
  args: {
    expectedProvider: tool.schema
      .string()
      .min(1)
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
          "--expect-provider",
          args.expectedProvider,
          "--overall-timeout",
          "120",
        ],
        {
          cwd: context.directory,
          env: process.env,
          stderr: "pipe",
          stdout: "pipe",
        },
      )
      const timeout = setTimeout(() => processResult.kill(), 125_000)
      const [stdout, exitCode] = await Promise.all([
        new Response(processResult.stdout).text(),
        processResult.exited,
      ]).finally(() => clearTimeout(timeout))
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
