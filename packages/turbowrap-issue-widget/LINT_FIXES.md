# Linting Issues Found

## 1. Unused Type Export (element-picker.ts)
- Line 3: `export type { ElementInfo }` is redundant - already imported from types

## 2. Silent Error Handling
- Multiple empty catch blocks that swallow errors without logging
- screen-capture.ts: Lines 18, 109, 140
- widget.ts: Lines 694, 812-814, 832-834, 867-869, 1148, 1293, 1303, 1342
- client.ts: Line 305

## 3. Magic Numbers
- Z-index values should be constants
- File size limits should be constants
- Array size limits are good (already defined)

## 4. Developer Comments in Production Code
- "HIGH ISSUE" comments should be removed (lines 38, 141, 474, 785, 796, 889, 974, 1034, 1084, 1136, 1193, 1240, 1288)

## 5. Type Safety
- Unsafe `as` casts in multiple locations
- Missing null checks before operations

## 6. console.debug in Production
- client.ts line 180: console.debug should be removed or use proper logging
