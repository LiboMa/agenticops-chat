# vendor/ —— 只给 3D 预览用的第三方文件

| 文件 | 是什么 | 版本 | 许可 | 来源 | sha256 |
|---|---|---|---|---|---|
| `3d-force-graph.min.js` | 3D 力导向图引擎（内含 three.js） | 1.80.2 | MIT | `https://unpkg.com/3d-force-graph@1.80.2/dist/3d-force-graph.min.js` | 见下 |

- **只有 `preview-3d.html` 用它。** 原型本体（`index.html`）、设计系统一览、自测页都不加载这个文件，仍然是零依赖。
- 放一份在仓库里而不是引用 CDN，是为了双击就能打开、没有网络也能看。
- 它和 `knowledge-graph-3d.tsx`（另一个项目的 3D 知识图谱组件）用的是同一个引擎：那个组件用的 `react-force-graph-3d` 就是它的 React 外壳。
- 这是预览用的。新界面正式要不要 3D、要不要加这个依赖（约 1.4 MB，其中 three.js 占大头），由主人看过预览后定；不要的话删掉这个目录和 `preview-3d.html`、`screens/world3d.js` 即可。

`3d-force-graph.min.js` sha256: `ae9b5ca9d525095978d0f5d23f9136dfe177b2e949773102ffbf145dd7776f04`
