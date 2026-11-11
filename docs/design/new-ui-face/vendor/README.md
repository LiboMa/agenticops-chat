# vendor/ —— 只给「全景」的 3D 看法用的第三方文件

| 文件 | 是什么 | 版本 | 许可 | 来源 | sha256 |
|---|---|---|---|---|---|
| `3d-force-graph.min.js` | 3D 力导向图引擎（内含 three.js） | 1.80.2 | MIT | `https://unpkg.com/3d-force-graph@1.80.2/dist/3d-force-graph.min.js` | 见下 |

- **只有「全景」的 3D 看法用它，而且是第一次切到 3D 时才加载**（`screens/sky3d.js` 动态插入脚本）。不切 3D 就永远不加载；原型的其他部分、设计系统一览、自测页都不依赖它。
- 放一份在仓库里而不是引用 CDN，是为了双击就能打开、没有网络也能看。
- 它和 `knowledge-graph-3d.tsx`（另一个项目的 3D 知识图谱组件）用的是同一个引擎：那个组件用的 `react-force-graph-3d` 就是它的 React 外壳。
- 主人 2026-11-11 定了：平面和 3D 两种看法都保留。正式实现时这是一个真实的依赖（约 1.4 MB，未经 gzip，其中 three.js 占大头），要按需加载。

`3d-force-graph.min.js` sha256: `ae9b5ca9d525095978d0f5d23f9136dfe177b2e949773102ffbf145dd7776f04`
