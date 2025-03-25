# History On Reload plugin for Langbot

解决重启 langbot、重载 LLM 后丢失对话上下文的问题。

## 安装方法

配置完成 [LangBot](https://github.com/RockChinQ/LangBot) 主程序后使用管理员账号向机器人发送命令即可安装：

```
!plugin get https://github.com/Sansui233/HistoryOnReload
```

## 使用方法

- 在 重启程序 后，加载插件自动会载入上次的活跃会话
- 在 重载 LLMModel 文件后，需要手动重载插件以载入上次的活跃会话（因为插件无法知道 LLMModel 被重载了）

判定机制是如果当前程序中没有任何会话，则在此插件加载时重载上次的活跃会话。

数据存储在 data/plugins/HistoryOnReload.db 中。


## Thinking

- [x] 在每次收到回复后进行 propmt 的本地存储。
- [x] 目前的回调时机非常不够用，回复后的 propmt 历史依然是没有更新的。所以只是在收到消息时重启还是会丢失最近的两句话。解决办法是更新 blob 时手动加。见 chat.py
- [x] 需要数据库锁
- [ ] 需有一个处理池，连续的同类型的请求只处理最后一个(插件只能被动延迟了)
- [x] 写入数据库时可能很难判断数据库里有没有对应的 uuid，不知道是 该 create 还是 update，最佳实践是什么(sqlite v3.42: upsert)
- [x] 需不需要存储其他插件修改后的 prompt？不需要。因为 preprocess prompt 通常视作与对话无关的临时信息，用户视角并不能感知到此历史的存在。所以要看，这个 conversation 持久化是什么视角的。我认为是用户视角，不需要插件修改后的临时 prompt 的信息。只是用户视角的持久化的信息，所以需要获取到 conversation 的更新。
- [x] 插件的位置也有问题，不能放在最后也不能放在最前。我认为做法是，放在回复是使用修改 langbot 原生 message 的插件之后，放在使用 send_message 的消息之前。但这也并不能代表用户视角，因为有的插件可能是根据大模型回复的内容去调用了不同的东西。比如用户发送“画猫”（需要记住），给大模型的消息是“生成画猫的提示词”（不需要记住）。这类不是使用 function call 而是破坏性修改了回复内容然后发送主动消息，即便是 langbot 原程序做持久化也没有什么办法。
- [x] conversation 直接用的 openai 的 message 字段格式。由于不同 LLM 会话消息种类不同，启动此插件后更换差异过大的 LLM，是不是有可能导致消息无法发出？但如果对 requester 对不支持消息链有丢弃也还好。没有测试。总之尽量使用同种消息链的 LLM。


