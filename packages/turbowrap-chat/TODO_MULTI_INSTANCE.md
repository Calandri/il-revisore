# TODO: Multi-Instance Refactoring for TurboWrap Chat

## Objective
Enable multiple `<ChatWidget />` instances to coexist in the same application with independent states (active session, settings, UI mode) while sharing the underlying API client logic if needed.

## Phase 1: Store Architecture Refactoring
- [ ] **Convert Singleton to Factory**
    - Modify `packages/turbowrap-chat/src/store/chat-store.ts`.
    - Rename `useChatStore` (the hook) to `createChatStore`.
    - It should return a *vanilla* Zustand store instance, not a hook.
    - Type definition: `export type ChatStoreApi = ReturnType<typeof createChatStore>;`.

## Phase 2: Context Provider Isolation
- [ ] **Update `ChatProvider`**
    - Modify `packages/turbowrap-chat/src/context/chat-provider.tsx`.
    - Remove the global import of `useChatStore`.
    - Use `useRef` to create a *unique* store instance per Provider mount:
      ```typescript
      const storeRef = useRef<ChatStoreApi>();
      if (!storeRef.current) {
        storeRef.current = createChatStore();
      }
      ```
    - Pass this store instance into a new `StoreContext`.

## Phase 3: Hook Consumption Updates
- [ ] **Create `useStore` Wrapper**
    - Create a standard pattern for accessing the context-injected store.
    - Replace all direct imports of `import { useChatStore } from '../store'` with a context-aware hook (e.g., `useChatStoreContext`).
- [ ] **Update Hooks**
    - Refactor `useChat` (`packages/turbowrap-chat/src/hooks/use-chat.ts`) to use the context store.
    - Refactor `useStreaming` (`packages/turbowrap-chat/src/hooks/use-streaming.ts`) to use the context store.

## Phase 4: Component Updates
- [ ] **Refactor `ChatWidget`**
    - Ensure `ChatWidget` initializes its own provider correctly.
    - Verify that `ChatWidgetInner` uses the context-based hooks.
- [ ] **Verify Selectors**
    - Ensure `selectors.ts` works with the new store instance pattern (it should be fine, as selectors are just functions, but consumption changes).

## Phase 5: Verification & Testing
- [ ] **Unit Test Update**
    - Update tests that mock the store to now mock the store factory or wrap components in the Provider.
- [ ] **Integration Test (The "Dual Chat" Test)**
    - Create a test page with **two** `ChatWidget` instances.
    - **Step 1:** Open Session A in Widget 1. Verify Widget 2 is unaffected (empty or showing Session B).
    - **Step 2:** Trigger streaming in Widget 1. Verify Widget 2 does not show Widget 1's streaming text.
    - **Step 3:** Change "Chat Mode" (Settings) in Widget 1. Verify Widget 2's settings remain unchanged.

## Optional / Advanced
- [ ] **Shared Worker Context**
    - If `SharedWorker` is used for global persistence, decide if it needs to broadcast to *specific* widget instances or if all widgets listening to the same `sessionId` should update in sync (which is usually desired).
