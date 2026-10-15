# 小栗 Android App 第一版

这是可安装的 Android 局域网演示客户端，不是把 Streamlit 页面套进浏览器。
Vue 界面打包在 APK 内，Capacitor 提供 Android 容器和系统拍照入口；Python 分析、
机型目录和 RAG 留在电脑。知识库导入、审核和发布页面仍在电脑的 8502 端口。

## 能做什么

- 拍照，或通过系统文件选择器选择 JPEG / PNG；上传前预览，不主动压缩相册文件。
- 输入风格、主体动作、手持 / 三脚架，选择手机 / 相机及已收录型号。
- 手机可选择型号支持的模式和镜头；专业模式需手动确认控制能力。
- 相机可按品牌/型号自动匹配画幅与卡口，选择已收录的原生兼容镜头后联动实际焦段、等效视角与保守光圈起点，后端再次校验；未选镜头仍可手填。
- 2026-10-14目录扩至14款相机、15款手机与12款可换镜头，详见 `docs/device-catalog-coverage.md`；新增机型的基础适配不代表所有曝光边界已核验。
- 展示场景、参数、解释、风险、试拍调整、检索依据；明确标记规则演示和云模型模式。
- 保存本机连接设置，可一键清除。不保存照片或分析历史到服务端。

## 第一次安装与连接

1. 将 `output/mobile/xiaoli-camera-assistant-debug.apk` 传到 Android 手机并打开。
   这是 debug 签名测试包，不是应用商店发行版；系统可能要求允许本次文件来源安装。
   当前最低 Android 7.0（API 24），实际使用还依赖可用且较新的 Android System WebView。
2. 电脑在项目根目录安装接口依赖：

   ```powershell
   python -m pip install -e ".[mobile]"
   ```

3. 双击根目录 `启动手机服务.cmd`，保持窗口运行；手机、电脑连接同一可信 Wi-Fi。
4. 用电脑 `ipconfig` 找到 Wi-Fi 的 IPv4，如 `192.168.1.20`。
5. 在 App「连接」填写 `http://192.168.1.20:8000`。
   不要填写 Streamlit 的 8501 / 8502，不要把电脑 localhost 地址复制到手机。
6. 打开项目 `.launcher/mobile-access.json`，将其中 `token` 的值复制到 App。
   此文件首次启动生成，已被 Git 忽略；它不是云模型 API Key。
   如 `.env` 配置了 `MOBILE_API_TOKEN`，则使用该值，不会使用文件中的备用值。
7. 点「保存并测试连接」，成功后进入拍摄页，选图、填写需求、同意上传并分析。

如果 Windows 防火墙询问访问权限，仅按演示需要允许**专用网络**。
本项目不会自动修改防火墙。访客 Wi-Fi / AP 隔离可能阻止手机连接电脑。
手动开发命令默认只监听 127.0.0.1；上面的 CMD 明确监听 0.0.0.0，供局域网访问。

### 确认分析方式

服务读取原 `.env`。`APP_DEMO_MODE=true` 或模型配置不完整时，是本地规则演示，
不是视觉模型理解照片，更不是准确率评测。
只有关闭演示并配置好密钥和两个模型名才启用现有云模型流程。
测试时可强制本地演示：

```powershell
python scripts/start_mobile_api.py --host 0.0.0.0 --demo
```

RAG 沿用 `KNOWLEDGE_RETRIEVAL_MODE`，不会因为安装 App 自动改为 managed、导入或发布资料。
当前 managed 主流程检索 scene / technique / equipment；构图库等的全链路融合仍属后续工作。
手机 legacy 分支不借用旧相机 Markdown 来推导手机手动参数。

## 工程与接口

```text
mobile/                         Vue / TypeScript 手机界面
  src/App.vue                   拍摄、建议、连接页面
  src/connection.mjs            服务地址与来源 URL 安全校验
  android/                      Capacitor Android 原生工程（含 Gradle wrapper）
src/camera_assistant/mobile_api.py  FastAPI，只开放分析和器材目录
scripts/start_mobile_api.py      启动入口与本机连接令牌
scripts/prepare_android.ps1     项目内 Android SDK / JDK 安装
scripts/build_android.ps1       构建、复制、验证 debug APK
tests/test_mobile_api.py        接口测试
mobile/tests/connection.test.mjs 地址校验测试
```

- `GET /health`：公开，只返回服务标识、版本、演示 / 云模式、图片上限。
- `GET /api/v1/devices`：需 `Authorization: Bearer <手机连接令牌>`。
- `POST /api/v1/analyze`：同样需令牌，multipart 字段为 `file`、`user_request`
  （原 UserRequest JSON）、`consent=true`、`expected_analysis_mode=demo|cloud`、
  `image_provenance=original_upload|device_camera`。分析方式改变会拒绝提交，要求重新确认说明。
  返回 `request_id`、`analysis_mode`、`image_provenance`、`result`。
- 401 令牌错误；409 分析模式改变；413 超大小；422 格式 / 同意 / 参数错误；429 并发繁忙；502 模型分析失败。
  不自动重试分析，避免重复上传或模型计费。

API 在解析 multipart 前鉴权，对 Content-Length 和分块正文同时限长，最多 4000 万像素，
限制同时分析 2 张。CORS 只允许本地 App 和开发界面来源，没有知识库管理接口和公开 API 文档。
结果不包含图片 base64 或模型密钥；外部错误内容不向客户端回显。
这是有边界的演示网关，不是生产级账户、限流或流式上传服务。

## 开发与重建 APK

需 Node.js 22+。Android 工程使用 JDK 21、Android SDK 36；安装 Build Tools 35.0.0
（当前 AGP 默认）和 36.0.0（签名与包检查工具）。先停止 Vite 开发服务，再运行需要 npm ci 的打包脚本。
工具均在 `.android-tools/`，只修改构建进程的环境变量，不改系统 Java / SDK 配置。
首次下载安装需要网络和数 GB 可用空间，必须先阅读并接受 Android SDK 许可：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_android.ps1 -AcceptAndroidSdkLicense
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_android.ps1
```

脚本会校验 SDK / JDK 下载散列；Gradle wrapper 固定版本并校验官方 SHA256。
如果下载中断或散列不匹配，脚本报错且不解压不可信文件；核实后移除对应下载缓存再重试。
APK 在 `mobile/android/app/build/outputs/apk/debug/app-debug.apk`，交付副本在 `output/mobile/`。
二进制、机器路径、工具缓存、签名文件和连接令牌不进入 Git。
若更换电脑导致 debug 签名不同，已有 App 可能无法覆盖安装；卸载会清除本机设置，先确认后操作。

本地浏览器开发与测试：

```powershell
python scripts/start_mobile_api.py --demo
cd mobile
npm.cmd ci
npm.cmd run dev
npm.cmd run build
npm.cmd test
```

电脑浏览器填写 `http://127.0.0.1:8000`；Android 模拟器可填写 `http://10.0.2.2:8000`
（电脑服务需监听相应接口）。不要将测试用令牌带入正式服务。

## 隐私、安全与当前边界

- APK 内无 `.env` 和云模型密钥。地址与手机令牌存在 WebView localStorage，**演示版未加密**，
  禁用 Android 备份；正式版本改为 KeyStore / 安全存储、用户登录与可撤销令牌。
- HTTP 仅用于可信局域网，App 拒绝公网 HTTP 地址。不要把电脑端口映射到公网。
  生产版本必须 HTTPS，去掉 cleartext 配置并建立账户、速率 / 内存限流和访问审计。
- 系统文件选择器提供的 JPEG / PNG 文件直接发送；拍照调用系统相机，可能经系统与插件处理。
  不承诺原始传感器文件或 EXIF 100% 保留。暂不支持 HEIC / HEIF / DNG / RAW。
- 云模式将缩小的照片副本发给配置的视觉模型；用户需求和相关知识发给建议模型。
  原分析网关不持久化照片，供应商是否留存以其政策为准。不要上传敏感图片。
- 建议不是自动控制手机相机，不实现实时预览 / 构图线 / 自动裁剪 / 曝光硬件控制。
  机型范围依赖现有能力目录，未知机型明确使用兜底，不推测相邻型号功能。
- 此版本是 Android debug 包；没有 iOS 包、正式签名、商店上架或线上常驻后端。
  浏览器流程通过不等于真机权限 / 相机返回 / 相册与所有 WebView 版本已验证。

## 本轮验证（2026-10-13）

- Python 回归测试 397 项通过、1 项跳过；其中手机接口测试 22 项通过。
- 前端地址校验 3 项通过，TypeScript 类型检查与 Vite 生产构建通过。
- Android `assembleDebug` 成功，`apksigner verify` 通过，包名
  `com.xiaoli.cameraassistant`、版本 `0.1.0`、最低 API 24 / 目标 API 36。
- 安装包有本地 HTML / JS 与小栗素材，没有 `.env`、数据库或测试连接令牌。
- Playwright 验证了手机尺寸下的选图、连接和规则演示分析。未调用收费云模型验证效果。
- `adb devices` 未发现设备；**未验证真机安装、相机返回与权限流程**，请按上述优先级验收。

## 下一版优先级

1. Android 真机验收：安装 / 返回键 / 拒绝权限 / 相册 EXIF / 系统拍照 / 网络断开。
2. 云端 HTTPS 后端与独立用户连接，摆脱必须开电脑的限制。
3. 增加构图结构化输出及静态叠加提示，先做可评测的离线建议，再做实时识别。
4. 接入构图 / 风格 / 案例等多库检索，测试条件过滤、重排和建议正确性。
5. 登录、安全存储、历史记录授权管理与正式发布签名。

实现参考：采用 [Capacitor 本地资源打包](https://capacitorjs.com/docs/getting-started)、
[Camera 拍照接口](https://capacitorjs.com/docs/apis/camera) 和
[FastAPI multipart 上传](https://fastapi.tiangolo.com/tutorial/request-forms-and-files/)。
工具来源：[Android 官方下载](https://developer.android.com/studio#command-tools)、
[Corretto 21 官方下载](https://docs.aws.amazon.com/corretto/latest/corretto-21-ug/downloads-list.html)、
[Gradle 官方校验值](https://gradle.org/release-checksums/)。

视觉方向：薄荷白 #F2F7F4、深绿 #20584C、正文 #203C35、次要文字 #657971、
珊瑚 #FF765B、分隔 #D8E5DD；使用本机中文字体。照片取景框与既有小栗素材是主视觉，
其余表单左对齐，底部三页导航，不使用远程字体或装饰性动画。
