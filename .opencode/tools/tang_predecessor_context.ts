type TangToolContext = {
  abort: AbortSignal
  directory: string
  sessionID: string
  worktree: string
}

type CommandResult = {
  output: string
  status: number
}

const unavailable = (code: string) =>
  JSON.stringify({ schema_version: 1, kind: "unavailable", code })

async function runTang(
  arguments_: string[],
  context: TangToolContext,
): Promise<CommandResult> {
  const child = Bun.spawn(arguments_, {
    cwd: context.directory,
    env: process.env,
    stderr: "ignore",
    stdout: "pipe",
  })
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
  const [output, status] = await Promise.all([
    new Response(child.stdout).text(),
    child.exited,
  ]).finally(() => {
    clearTimeout(timeout)
    context.abort.removeEventListener("abort", terminate)
  })
  return { output: output.trim(), status }
}

export default {
  description:
    "Read the active OpenCode session's confirmed Tang predecessors as one private Context Pack.",
  args: {},
  async execute(_args: Record<string, never>, context: TangToolContext) {
    const tang = process.env.TANG_EXECUTABLE ?? "tang"
    const executable = process.env.TANG_OPENCODE_EXECUTABLE ?? "opencode"
    try {
      const target = await runTang(
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
        context,
      )
      if (!target.output) return unavailable("tool-unavailable")
      let document: unknown
      try {
        document = JSON.parse(target.output)
      } catch {
        return unavailable("tool-unavailable")
      }
      if (
        !document ||
        typeof document !== "object" ||
        (document as { schema_version?: unknown }).schema_version !== 1 ||
        (document as { kind?: unknown }).kind !== "confirmation_required" ||
        (document as { code?: unknown }).code !== "host-id-match" ||
        (document as { candidate_count?: unknown }).candidate_count !== 1 ||
        !/^[A-Z][1-9][0-9]*$/.test(
          String((document as { target_handle?: unknown }).target_handle ?? ""),
        )
      ) {
        return target.output
      }
      const targetHandle = String(
        (document as { target_handle: unknown }).target_handle,
      )
      const recovered = await runTang(
        [
          tang,
          "context",
          "all",
          "--for",
          targetHandle,
          "--json",
          "--cwd",
          context.directory,
          "--opencode-executable",
          executable,
        ],
        context,
      )
      if (recovered.status !== 0 || !recovered.output) {
        return unavailable("predecessor-context-unavailable")
      }
      return recovered.output
    } catch {
      return unavailable("tool-unavailable")
    }
  },
}
