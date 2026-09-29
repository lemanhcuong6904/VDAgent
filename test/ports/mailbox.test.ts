import { beforeEach, describe, expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import {
  type HandoffItem,
  InMemoryMailbox,
  type Message,
  type Question,
  type Result,
  type WaitForEdge,
  type Wake,
} from "../../src/ports/mailbox.js";
import { testScope } from "../helpers/scope.js";

describe("Mailbox", () => {
  let mailbox: InMemoryMailbox;
  let scope: AgentScope;

  beforeEach(() => {
    mailbox = new InMemoryMailbox();
    scope = testScope({ actorId: "actor-1" });
  });

  describe("Question/Answer Flow", () => {
    it("should send a question and receive it", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
        timeoutMs: 5000,
      };

      const message: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      const { messageId, questionId } = await mailbox.ask(message);

      expect(messageId).toBe("msg-1");
      expect(questionId).toBe("q-1");

      const messages = await mailbox.receive("agent-b");
      expect(messages).toHaveLength(1);
      expect(messages[0].content).toMatchObject({ questionId: "q-1" });
    });

    it("should answer a question", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const questionMsg: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(questionMsg);

      const result: Result = {
        type: "result",
        questionId: "q-1",
        status: "success",
        output: { result: "done" },
      };

      const resultMsg: Message<Result> = {
        messageId: "msg-2",
        fromAgentId: "agent-b",
        toAgentId: "agent-a",
        scope,
        content: result,
        timestamp: new Date().toISOString(),
      };

      const { delivered } = await mailbox.answer(resultMsg);

      expect(delivered).toBe(true);

      const messages = await mailbox.receive("agent-a");
      expect(messages).toHaveLength(1);
      expect((messages[0].content as Result).status).toBe("success");
    });

    it("should wait for result", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const questionMsg: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(questionMsg);

      // Answer asynchronously
      setTimeout(async () => {
        const result: Result = {
          type: "result",
          questionId: "q-1",
          status: "success",
          output: { result: "done" },
        };

        const resultMsg: Message<Result> = {
          messageId: "msg-2",
          fromAgentId: "agent-b",
          toAgentId: "agent-a",
          scope,
          content: result,
          timestamp: new Date().toISOString(),
        };

        await mailbox.answer(resultMsg);
      }, 50);

      const resultMsg = await mailbox.waitForResult("agent-a", "q-1", 5000);

      expect(resultMsg).not.toBeNull();
      expect((resultMsg!.content as Result).status).toBe("success");
    });

    it("should timeout waiting for result", async () => {
      const resultMsg = await mailbox.waitForResult("agent-a", "q-nonexistent", 100);

      expect(resultMsg).toBeNull();
    });

    it("should remove wait-for edge when answering", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const questionMsg: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(questionMsg);

      let graph = await mailbox.getWaitForGraph();
      expect(graph).toHaveLength(1);
      expect(graph[0].questionId).toBe("q-1");

      const result: Result = {
        type: "result",
        questionId: "q-1",
        status: "success",
        output: { result: "done" },
      };

      const resultMsg: Message<Result> = {
        messageId: "msg-2",
        fromAgentId: "agent-b",
        toAgentId: "agent-a",
        scope,
        content: result,
        timestamp: new Date().toISOString(),
      };

      await mailbox.answer(resultMsg);

      graph = await mailbox.getWaitForGraph();
      expect(graph).toHaveLength(0);
    });
  });

  describe("Wake Notifications", () => {
    it("should send wake notification", async () => {
      const wake: Wake = {
        type: "wake",
        reason: "work_available",
        data: { workId: "w-1" },
      };

      const message: Message<Wake> = {
        messageId: "msg-1",
        fromAgentId: "coordinator",
        toAgentId: "worker",
        scope,
        content: wake,
        timestamp: new Date().toISOString(),
      };

      const { delivered } = await mailbox.wake(message);

      expect(delivered).toBe(true);

      const messages = await mailbox.receive("worker");
      expect(messages).toHaveLength(1);
      expect((messages[0].content as Wake).reason).toBe("work_available");
    });
  });

  describe("Deduplication", () => {
    it("should reject duplicate question", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const message: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(message);

      await expect(mailbox.ask(message)).rejects.toThrow("already processed");
    });

    it("should bounce duplicate answer", async () => {
      const result: Result = {
        type: "result",
        questionId: "q-1",
        status: "success",
        output: { result: "done" },
      };

      const message: Message<Result> = {
        messageId: "msg-1",
        fromAgentId: "agent-b",
        toAgentId: "agent-a",
        scope,
        content: result,
        timestamp: new Date().toISOString(),
      };

      const first = await mailbox.answer(message);
      expect(first.delivered).toBe(true);

      const second = await mailbox.answer(message);
      expect(second.delivered).toBe(false);
    });

    it("should bounce duplicate wake", async () => {
      const wake: Wake = {
        type: "wake",
        reason: "test",
      };

      const message: Message<Wake> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: wake,
        timestamp: new Date().toISOString(),
      };

      const first = await mailbox.wake(message);
      expect(first.delivered).toBe(true);

      const second = await mailbox.wake(message);
      expect(second.delivered).toBe(false);
    });

    it("should check if message is duplicate", async () => {
      const isDup1 = await mailbox.isDuplicate("msg-1");
      expect(isDup1).toBe(false);

      await mailbox.markProcessed("msg-1");

      const isDup2 = await mailbox.isDuplicate("msg-1");
      expect(isDup2).toBe(true);
    });
  });

  describe("Handoff with CAS", () => {
    it("should add and claim work item", async () => {
      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);

      const { success, item: claimed } = await mailbox.claimWork("item-1", "worker-1", 0);

      expect(success).toBe(true);
      expect(claimed!.status).toBe("claimed");
      expect(claimed!.ownerId).toBe("worker-1");
      expect(claimed!.version).toBe(1);
    });

    it("should fail to claim with wrong version (CAS)", async () => {
      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);

      // First claim succeeds
      await mailbox.claimWork("item-1", "worker-1", 0);

      // Second claim with old version fails
      const { success } = await mailbox.claimWork("item-1", "worker-2", 0);

      expect(success).toBe(false);
    });

    it("should complete work item", async () => {
      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);
      await mailbox.claimWork("item-1", "worker-1", 0);

      const { success } = await mailbox.completeWork("item-1", "worker-1");

      expect(success).toBe(true);
    });

    it("should fail to complete if not owner", async () => {
      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);
      await mailbox.claimWork("item-1", "worker-1", 0);

      const { success } = await mailbox.completeWork("item-1", "worker-2");

      expect(success).toBe(false);
    });

    it("should release work item", async () => {
      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);
      await mailbox.claimWork("item-1", "worker-1", 0);

      const { success } = await mailbox.releaseWork("item-1", "worker-1");

      expect(success).toBe(true);

      const available = await mailbox.getAvailableWork();
      expect(available).toHaveLength(1);
      expect(available[0].status).toBe("available");
      expect(available[0].ownerId).toBeNull();
      expect(available[0].version).toBe(2);
    });

    it("should get available work by type", async () => {
      await mailbox.addWorkItem({
        itemId: "item-1",
        workType: "analysis",
        payload: {},
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      });

      await mailbox.addWorkItem({
        itemId: "item-2",
        workType: "formatting",
        payload: {},
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      });

      const analysis = await mailbox.getAvailableWork("analysis");
      expect(analysis).toHaveLength(1);
      expect(analysis[0].workType).toBe("analysis");

      const all = await mailbox.getAvailableWork();
      expect(all).toHaveLength(2);
    });
  });

  describe("Wait-For Cycle Detection", () => {
    it("should detect simple cycle", async () => {
      const edge1: WaitForEdge = {
        waitingAgentId: "agent-a",
        blockedOnAgentId: "agent-b",
        questionId: "q-1",
        since: new Date().toISOString(),
      };

      await mailbox.addWaitFor(edge1);

      // Try to create cycle: b -> a (when a -> b already exists)
      const wouldCycle = await mailbox.wouldCreateCycle("agent-b", "agent-a");

      expect(wouldCycle).toBe(true);
    });

    it("should detect transitive cycle", async () => {
      // a -> b
      await mailbox.addWaitFor({
        waitingAgentId: "agent-a",
        blockedOnAgentId: "agent-b",
        questionId: "q-1",
        since: new Date().toISOString(),
      });

      // b -> c
      await mailbox.addWaitFor({
        waitingAgentId: "agent-b",
        blockedOnAgentId: "agent-c",
        questionId: "q-2",
        since: new Date().toISOString(),
      });

      // Try to create cycle: c -> a (would create a -> b -> c -> a)
      const wouldCycle = await mailbox.wouldCreateCycle("agent-c", "agent-a");

      expect(wouldCycle).toBe(true);
    });

    it("should allow non-cyclic edge", async () => {
      // a -> b
      await mailbox.addWaitFor({
        waitingAgentId: "agent-a",
        blockedOnAgentId: "agent-b",
        questionId: "q-1",
        since: new Date().toISOString(),
      });

      // c -> d is independent, no cycle
      const wouldCycle = await mailbox.wouldCreateCycle("agent-c", "agent-d");

      expect(wouldCycle).toBe(false);
    });

    it("should reject ask that would create cycle", async () => {
      // a -> b
      const question1: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const msg1: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question1,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(msg1);

      // Try b -> a (would create cycle)
      const question2: Question = {
        type: "question",
        questionId: "q-2",
        input: { task: "test" },
      };

      const msg2: Message<Question> = {
        messageId: "msg-2",
        fromAgentId: "agent-b",
        toAgentId: "agent-a",
        scope,
        content: question2,
        timestamp: new Date().toISOString(),
      };

      await expect(mailbox.ask(msg2)).rejects.toThrow("would create wait-for cycle");
    });

    it("should get wait-for graph", async () => {
      await mailbox.addWaitFor({
        waitingAgentId: "agent-a",
        blockedOnAgentId: "agent-b",
        questionId: "q-1",
        since: new Date().toISOString(),
      });

      await mailbox.addWaitFor({
        waitingAgentId: "agent-b",
        blockedOnAgentId: "agent-c",
        questionId: "q-2",
        since: new Date().toISOString(),
      });

      const graph = await mailbox.getWaitForGraph();

      expect(graph).toHaveLength(2);
      expect(graph.map((e) => e.questionId).sort()).toEqual(["q-1", "q-2"]);
    });

    it("should remove wait-for edge", async () => {
      await mailbox.addWaitFor({
        waitingAgentId: "agent-a",
        blockedOnAgentId: "agent-b",
        questionId: "q-1",
        since: new Date().toISOString(),
      });

      let graph = await mailbox.getWaitForGraph();
      expect(graph).toHaveLength(1);

      await mailbox.removeWaitFor("q-1");

      graph = await mailbox.getWaitForGraph();
      expect(graph).toHaveLength(0);
    });
  });

  describe("Message Receive", () => {
    it("should receive multiple messages", async () => {
      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      await mailbox.ask({
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      });

      await mailbox.wake({
        messageId: "msg-2",
        fromAgentId: "coordinator",
        toAgentId: "agent-b",
        scope,
        content: { type: "wake", reason: "test" },
        timestamp: new Date().toISOString(),
      });

      const messages = await mailbox.receive("agent-b");

      expect(messages).toHaveLength(2);
    });

    it("should receive limited number of messages", async () => {
      for (let i = 0; i < 5; i++) {
        await mailbox.wake({
          messageId: `msg-${i}`,
          fromAgentId: "coordinator",
          toAgentId: "worker",
          scope,
          content: { type: "wake", reason: "test" },
          timestamp: new Date().toISOString(),
        });
      }

      const messages = await mailbox.receive("worker", 2);

      expect(messages).toHaveLength(2);

      const remaining = await mailbox.receive("worker");
      expect(remaining).toHaveLength(3);
    });

    it("should return empty array for agent with no messages", async () => {
      const messages = await mailbox.receive("nonexistent");

      expect(messages).toHaveLength(0);
    });
  });
});
