# workflows/

运行时目录：存放从 RunningHub 工作台「导出工作流 API」得到的原始 JSON。

- 命名：`<workflowId>.json`
- 用途：任务类型校验的真相来源（核对 nodeId / fieldName 是否存在），可很大。
- `<workflowId>.json` 归档随仓库公开提交；非归档命名的原始导出仅作本地参考，可不入库。
