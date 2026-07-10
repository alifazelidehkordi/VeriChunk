export function buildReviewerArgs(options = {}, env = process.env) {
  const backend = options.backend || env.DOC_SPLITTER_REVIEW_BACKEND || "command";
  const args = ["run-topic-reviews", "--backend", backend];

  if (backend === "command") {
    const command = env.DOC_SPLITTER_AGENT_COMMAND || "";
    if (!command) {
      throw new Error("DOC_SPLITTER_AGENT_COMMAND is not configured for command reviews");
    }
    args.push("--agent-command", command);
  } else if (backend === "openai") {
    const model = options.model || env.DOC_SPLITTER_OPENAI_MODEL || "";
    if (!model) {
      throw new Error("model or DOC_SPLITTER_OPENAI_MODEL is required for OpenAI reviews");
    }
    args.push("--model", model);
    if (env.DOC_SPLITTER_OPENAI_BASE_URL) {
      args.push("--base-url", env.DOC_SPLITTER_OPENAI_BASE_URL);
    }
  } else if (backend === "anthropic") {
    const model = options.model || env.DOC_SPLITTER_ANTHROPIC_MODEL || "";
    if (!model) {
      throw new Error("model or DOC_SPLITTER_ANTHROPIC_MODEL is required for Anthropic reviews");
    }
    args.push("--model", model);
    if (env.DOC_SPLITTER_ANTHROPIC_BASE_URL) {
      args.push("--base-url", env.DOC_SPLITTER_ANTHROPIC_BASE_URL);
    }
  } else {
    throw new Error(`Unsupported review backend: ${backend}`);
  }

  if (options.output_dir) args.push("--out", options.output_dir);
  if (options.workers) args.push("--workers", String(options.workers));
  if (options.timeout_seconds) args.push("--timeout-seconds", String(options.timeout_seconds));
  if (options.retries !== undefined) args.push("--retries", String(options.retries));
  if (options.max_output_bytes !== undefined && backend === "command") {
    args.push("--agent-max-output-bytes", String(options.max_output_bytes));
  }
  if (options.max_output_tokens !== undefined && backend !== "command") {
    args.push("--max-output-tokens", String(options.max_output_tokens));
  }
  return args;
}
