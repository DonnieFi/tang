import path from "node:path"
import { tool } from "@opencode-ai/plugin"

export default tool({
  description:
    "Probe Tang's OpenCode source/current-session contract without returning IDs, paths, titles, transcript text, tool values, or credentials.",
  args: {},
  async execute(_args, context) {
    const script = path.join(
      context.worktree,
      "scripts",
      "probe_opencode_contract.py",
    )
    const executable = process.env.TANG_OPENCODE_EXECUTABLE ?? "opencode"
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
      ],
      {
        cwd: context.directory,
        env: process.env,
        stderr: "pipe",
        stdout: "pipe",
      },
    )
    const [stdout, exitCode] = await Promise.all([
      new Response(processResult.stdout).text(),
      processResult.exited,
    ])
    if (exitCode !== 0 && stdout.trim().length === 0) {
      return JSON.stringify({
        schema_version: 1,
        result: "fail",
        error: "Tang's OpenCode contract probe could not run; raw output withheld",
      })
    }
    return stdout.trim()
  },
})
