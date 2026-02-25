# PaperViz PDF Service

## 一、 服务名称与简介
PaperViz PDF Service 是一个独立的微服务，主要用于提供稳定、高效的 PDF 文档解析与内容提取能力。作为 PaperViz 架构中的基础组件，该服务通过 REST API 提供无状态的 PDF 处理接口，处理任务经由 Celery 异步派发后台执行。

## 二、 上游开源项目信息
本服务核心的 PDF 解析能力依赖于以下优秀的开源项目：
- **项目名称**：PyMuPDF 
- **项目仓库**：[https://github.com/pymupdf/PyMuPDF](https://github.com/pymupdf/PyMuPDF)
- **开源协议**：**GNU Affero General Public License v3.0 (AGPL-3.0)**
- **版权声明**：Copyright © 2023 Artifex Software, Inc.

## 三、 本服务用途
本微服务并非通用的客户端工具，而是被设计为封装级的后台网络服务。主要功能包括：
- **PDF 加载与解析**：安全读取与初始化文档基础属性。
- **文本 / 表格提取**：结构化地将 PDF 视觉排版转化为文本或 Markdown 数据。
- **渲染与转换**：按需提供流式转换与块级内容分割。

通过本微服务将 PyMuPDF 封装为内部 HTTP API 后，PaperViz 成功实现了复杂 PDF 处理逻辑的拆分与独立部署。

## 四、 AGPL-3.0 协议说明与合规声明
> **重要合规声明**：本服务（PaperViz PDF Service）本身衍生自基于 AGPL-3.0 协议发布的 PyMuPDF。为严格遵循环保开源的法律约定，**本微服务的全部源代码受 GNU Affero General Public License v3.0 (AGPL-3.0) 约束并予以完全开源**。

AGPL-3.0 的核心特征与您（作为二次开发者或服务部署者）的义务包括：
1. **网络服务公开源码（Network Service Obligation）**：如果您修改了本服务代码，并将其通过网络形式（作为 SaaS 后端、微服务 API）向外部提供服务，您**必须**向通过网络使用该服务的用户提供修改后的完整源代码的获取方式（例如在响应中或前端页面提供本代码仓库的下载链接）。
2. **同源传染性（Copyleft）**：如果您提取本代码的任意部分并修改或合并到您的闭源项目中，则您的整个派生项目都必须以 AGPL-3.0 协议开源。
3. **协议包含**：您在分发、部署此代码时，必须保留上游项目的版权声明及本声明条款。

附录条款全文：[GNU AGPL-3.0 License 原文](https://www.gnu.org/licenses/agpl-3.0.html)

## 五、 部署与使用简要说明
本微服务采用 `FastAPI` + `Celery` + `Redis` 架构。
**环境要求**：
- Python 3.11+
- Redis (作为 Celery Broker 和 Backend)

**快速启动**：
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 FastAPI 接口
uvicorn main:app --host 0.0.0.0 --port 8000

# 3. 启动 Celery Worker
celery -A celery_app worker --loglevel=info
```
*注：具体依赖的上游服务地址及凭据请参考配置文件或 `.env.example`。建议本服务仅对内部网络部署。*

## 六、 合规提示
- **源码获取**：您当前看到的仓库即为本服务的完整开源代码，任何人都可以自由获取、使用与学习。
- **修改反馈**：如您发现任何 Bug、有优化建议，欢迎直接向本仓库提交 Pull Request (PR) 或是 Issue。
- **主产品声明**：本仓库仅涵盖调用 PyMuPDF 的独立微服务层逻辑。PaperViz 的主业务逻辑栈通过标准 HTTP API 进行隔离交互，主业务栈为商业私有代码。

## 七、 版权声明与致谢
感谢 PyMuPDF 团队及 Artifex Software 开发了强大且跨平台的 PDF 解析器。
This service uses PyMuPDF under the AGPL-3.0 license. We thank the original authors for their continuous contributions to the open-source community.
