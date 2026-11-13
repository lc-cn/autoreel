# 第三方组件与授权

AutoClip 自身代码以 MIT 协议发布。以下第三方组件在运行时由 `tools/setup.sh` 下载或调用，本仓库**不包含**它们的副本，它们各自遵循自己的协议。

## 运行时依赖

| 组件 | 用途 | 协议 |
|---|---|---|
| [HyperFrames](https://github.com/heygen-com/hyperframes) | HTML → 视频渲染 | Apache-2.0 |
| [GSAP](https://gsap.com/) | 画面动画 | GSAP Standard License（免费，含商用） |
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | 离线语音合成（代码与模型） | Apache-2.0 |
| [PyTorch](https://pytorch.org/) | CosyVoice 运行环境 | BSD-3-Clause |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 轻量离线语音合成 | Apache-2.0 |
| [文泉驿正黑](http://wenq.org/) | 中文字体 | GPL-2.0（附字体嵌入例外） |
| fontTools、Pillow、NumPy、soundfile、rjieba 等 | Python 工具库 | 各自开源协议 |

## 配音

| 方案 | 授权说明 |
|---|---|
| 火山引擎豆包语音 `volcengine` | 商业云服务，按[火山引擎服务条款](https://www.volcengine.com/docs/6561)使用；需要你自己开通、付费，音色使用范围以火山引擎协议为准 |
| CosyVoice `cosyvoice` | 模型以 Apache-2.0 发布。用参考录音复刻音色时，**只能使用你本人或已获授权的声音** |
| sherpa · Kokoro | [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)，Apache-2.0；训练语料来自龙猫数据（LongMaoData），我们未找到语料的单独授权说明 |
| sherpa · MeloTTS | MIT |
| sherpa · baker | 模型代码 Apache-2.0；**训练数据为标贝中文标准女声语音库，仅授权非商业使用，不建议商用** |

## 参考的开源项目

- [social-auto-upload](https://github.com/dreammis/social-auto-upload)（MIT）：浏览器插件中抖音、视频号、快手上传页面的操作流程（元素定位、上传进度判断、自主声明、合集、封面弹窗处理）参考了该项目，并按插件运行环境重新实现。

  > Copyright (c) dreammis and contributors. Licensed under the MIT License.

## 内容数据

视频中的资讯、知识、书评由 AI 根据公开资料整理，版权归原作者与原媒体所有，发布文案中标注了来源。好物类内容只使用用户提供的资料。
