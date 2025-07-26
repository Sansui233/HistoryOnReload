import asyncio
import os
import typing
import uuid

from pkg.core.entities import LauncherTypes, Query, Session
from pkg.plugin.context import APIHost, BasePlugin, EventContext, handler, register
from pkg.plugin.events import NormalMessageResponded
from .database import HistoryDataBase
from .type import ConversationItem, ConversationSchema


@register(
    name="HistoryOnReload",  # 英文名
    description="历史记录持久化，重启时加载上一次会话",  # 中文描述
    version="0.1.0",
    author="Sansui233",
)
class HistoryOnReload(BasePlugin):
    def __init__(self, host: APIHost):
        global db, db_lock
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

            for item in items:
                item = typing.cast(ConversationSchema, item)
                conversation_item = typing.cast(ConversationItem, item.conversation)
                conversation_item = conversation_item._to_conversation(
                    use_funcs=await self.ap.tool_mgr.get_all_functions(
                        plugin_enabled=True,
                    ),
                )
                (launcher_type, launcher_id) = parse_session_name(
                    item.session_name  # type: ignore
                )
                session_concurrency = self.ap.instance_config.data["concurrency"][
                    "session"
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
            for s in self.ap.sess_mgr.session_list:
                self.ap.logger.info(
                    f"[HistoryOnReload] 会话 {str(s.launcher_type.value)}_{s.launcher_id} message 数： {len(s.using_conversation.messages)}"  # type:ignore
                )

            # 清理数据库中不活跃的会话
            await self.db.del_item_unused()

    @handler(NormalMessageResponded)
    async def on_normal_message_responded(self, ctx: EventContext):
        ctx.event.query = typing.cast(Query, ctx.event.query)
        evt = typing.cast(NormalMessageResponded, ctx.event)

        session_name = (
            f"{ctx.event.query.launcher_type.value}_{ctx.event.query.launcher_id}"
        )
        conversation = await self.ap.sess_mgr.get_conversation(evt.query, evt.session, evt.query.pipeline_config['ai']['local-agent']['prompt'], evt.query.pipeline_uuid, evt.query.bot_uuid)
        if conversation.uuid is None:
            conversation.uuid = str(uuid.uuid4())

        # append current
        saved_conversation = conversation.copy()
        saved_conversation.messages = saved_conversation.messages.copy()
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
            await self.db.update_in_use_status(
                session_name, str(saved_conversation.uuid)
            )
            # self.ap.logger.info(f"[HistoryOnReload] Upsert result: {res}")


def parse_session_name(session_name: str) -> tuple[LauncherTypes, str]:
    launcher_type, launcher_id = session_name.split("_", 1)
    launcher_type = (
        LauncherTypes.PERSON if launcher_type == "person" else LauncherTypes.GROUP
    )
    return (launcher_type, launcher_id)
