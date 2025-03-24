import asyncio
import os
import typing
import uuid

from pkg.command.operator import CommandOperator, operator_class
from pkg.core.entities import Conversation, Query, Session
from pkg.plugin.context import APIHost, BasePlugin, EventContext, handler, register
from pkg.plugin.events import NormalMessageResponded
from plugins.HistoryOnReload.database import HistoryDataBase
from plugins.HistoryOnReload.type import ConversationItem, ConversationSchema


@register(
    name="HistoryOnReload",  # 英文名
    description="历史记录持久化，重载时加载上一次 conversation",  # 中文描述
    version="0.1.0",
    author="Sansui233",
)
class HistoryOnReload(BasePlugin):
    def __init__(self, host: APIHost):
        self.db_path = os.path.join("data", "plugins", "HistoryOnReload.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = HistoryDataBase()
        self.db_lock = asyncio.Lock()

    async def initialize(self):
        async with self.db_lock:
            await self.db.initialize(self.db_path)

        if len(self.ap.sess_mgr.session_list) == 0:
            await self.load()
        self.ap.logger.info("🧩 [HistoryOnReload] 插件初始化")

    async def load(self):
        # 如果会话全不存在，则从历史记录中加载会话
        self.ap.logger.info("[HistoryOnReload] 加载历史记录中的活跃会话...\n")

        async with self.db_lock:
            items = await self.db.get_in_use_conversations()
            self.ap.logger.info(f"item: {items}")

            for item in items:
                self.ap.logger.info(f"typof(item.conversation): {type(item)}")
                conversation_item = typing.cast(ConversationSchema, item.conversation)
                conversation_item = conversation_item._to_conversation(
                    use_model=await self.ap.model_mgr.get_model_by_name(
                        self.ap.provider_cfg.data["model"]
                    ),
                    use_funcs=await self.ap.tool_mgr.get_all_functions(
                        plugin_enabled=True,
                    ),
                )
                (launcher_type, launcher_id) = self.parse_session_name(
                    item.session_name  # type: ignore
                )
                session_concurrency = self.ap.system_cfg.data["session-concurrency"][
                    "default"
                ]
                session = Session(
                    launcher_type=launcher_type,  # type: ignore
                    launcher_id=launcher_id,
                    semaphore=asyncio.Semaphore(session_concurrency),
                )
                session.conversations = [conversation_item]
                session.using_conversation = conversation_item
                self.ap.sess_mgr.session_list.append(session)

            self.ap.logger.info(f"[HistoryOnReload] 加载 {len(items)} 个活跃会话\n")

            # 清理数据库中不活跃的会话
            await self.db.del_item_unused()

    @handler(NormalMessageResponded)
    async def on_normal_message_responded(self, ctx: EventContext):
        ctx.event.query = typing.cast(Query, ctx.event.query)
        evt = typing.cast(NormalMessageResponded, ctx.event)

        session_name = (
            f"{ctx.event.query.launcher_type.value}_{ctx.event.query.launcher_id}"
        )
        conversation = await self.ap.sess_mgr.get_conversation(evt.session)
        if conversation.uuid is None:
            conversation.uuid = str(uuid.uuid4())

        # append current
        saved_conversation = conversation.copy()
        if ctx.event.query.user_message and ctx.event.query.resp_messages:
            saved_conversation.messages.append(ctx.event.query.user_message)
            saved_conversation.messages.extend(ctx.event.query.resp_messages)  # type: ignore . message chain 是 iterable 的

        # save to db
        async with self.db_lock:
            res = await self.db.upsert_conversation(
                session_name,
                ConversationItem._from_conversation(saved_conversation),
                in_use=True,
            )
            self.ap.logger.info(f"[HistoryOnReload] Upsert result: {res}")

    def parse_session_name(self, session_name: str) -> tuple[str, str]:
        launcher_type, launcher_id = session_name.split("_", 1)
        return (launcher_type, launcher_id)
