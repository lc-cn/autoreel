# 用自己的电脑定时出片

适合：AI 工具装在自己电脑上，没有定时任务功能；或者有显卡，想配音更快。**电脑要在制作时间开着、联网。**

## 准备

1. 把仓库 clone 到电脑上，运行一次 `bash tools/setup.sh`。
2. 复制配置：`cp schedulers/local/agent.env.example schedulers/local/agent.env`，按你的 AI 工具取消注释一组 `AGENT_CMD`，需要的话填 API 密钥。这个文件不会被提交。
3. 确认 `git push` 不用输密码（用 SSH 密钥或 `gh auth login`）。
4. 手动试一次：`schedulers/local/run.sh kuaibao`，日志在 `schedulers/local/logs/`。

## Linux：crontab

`crontab -e`，每个频道一行（下面是北京时间；系统时区不是北京时间时，第一行的 `CRON_TZ` 在 cronie 等实现里可用，否则自己换算）：

```
CRON_TZ=Asia/Shanghai
0 8 * * *  /path/to/仓库/schedulers/local/run.sh kuaibao
30 11 * * * /path/to/仓库/schedulers/local/run.sh jiangtou
0 18 * * * /path/to/仓库/schedulers/local/run.sh lishi
```

## macOS：launchd

每个频道一个文件 `~/Library/LaunchAgents/com.autoreel.<频道>.plist`（时间是电脑本地时间）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.autoreel.kuaibao</string>
  <key>ProgramArguments</key><array>
    <string>/path/to/仓库/schedulers/local/run.sh</string><string>kuaibao</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
</dict></plist>
```

然后 `launchctl load ~/Library/LaunchAgents/com.autoreel.kuaibao.plist`。电脑睡眠时错过的任务会在唤醒后补跑。
