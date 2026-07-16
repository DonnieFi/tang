type TangToolContext = {
  abort: AbortSignal
  directory: string
  sessionID: string
  worktree: string
}

export default {
  description: "Resolve the active OpenCode session to a privacy-safe Tang target handle.",
  args: {},
  async execute(_args: Record<string, never>, context: TangToolContext) {
    const tang = process.env.TANG_EXECUTABLE ?? "tang"
    const executable = process.env.TANG_OPENCODE_EXECUTABLE ?? "opencode"
    try {
      const child = Bun.spawn(
        [
          tang,
          "skill",
          "opencode-target",
          "--json",
          "--cwd",
          context.directory,
          "--worktree",
          context.worktree,
          "--session-id",
          context.sessionID,
          "--opencode-executable",
          executable,
        ],
        { cwd: context.directory, env: process.env, stderr: "ignore", stdout: "pipe" },
      )
      const terminate = () => {
        try {
          child.kill()
        } catch {
          // The process may have exited between the signal and this callback.
        }
      }
      context.abort.addEventListener("abort", terminate, { once: true })
      if (context.abort.aborted) terminate()
      const timeout = setTimeout(terminate, 35_000)
      const [output] = await Promise.all([
        new Response(child.stdout).text(),
        child.exited,
      ]).finally(() => {
        clearTimeout(timeout)
        context.abort.removeEventListener("abort", terminate)
      })
      return output.trim() || JSON.stringify({ schema_version: 1, kind: "unavailable", code: "tool-unavailable" })
    } catch {
      return JSON.stringify({ schema_version: 1, kind: "unavailable", code: "tool-unavailable" })
    }
  },
}
