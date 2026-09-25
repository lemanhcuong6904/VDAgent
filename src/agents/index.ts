import type { AgentPlugin } from "../agent-contract.js";
import { agentPlugin as compare } from "./compare/index.js";
import { agentPlugin as data } from "./data/index.js";
import { agentPlugin as insight } from "./insight/index.js";
import { agentPlugin as orchestrator } from "./orchestrator/index.js";
import { agentPlugin as report } from "./report/index.js";
import { agentPlugin as visualize } from "./visualize/index.js";

export const plugins: AgentPlugin[] = [orchestrator, data, compare, insight, visualize, report];
