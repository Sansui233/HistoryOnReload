import time
import typing

from sqlalchemy import (
    and_,
    case,
    delete,
    literal_column,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from .type import Base, ConversationItem, ConversationSchema


# DB CURD，需要 sqlite > 3.24
async def _init_db(db_path: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
    return engine


class HistoryDataBase:
    def __init__(self):
        self.engine = None

    async def initialize(self, db_path: str):
        self.engine = await _init_db(db_path)

    async def upsert_conversation(
        self,
        session_name: str,
        conversation: ConversationItem,
        in_use: bool = False,
    ) -> str | typing.Literal[False]:
        """创建或更新条目，返回操作后的状态或 False，False 表示 Upsert 失败"""
        async with AsyncSession(self.engine) as conn:
            # 构造插入语句
            stmt = insert(ConversationSchema).values(
                uuid=conversation.uuid,
                session_name=session_name,
                conversation=conversation,
                in_use=in_use,
                timestamp=str(time.time()),
            )
            # 定义冲突时的更新逻辑
            update_stmt = stmt.on_conflict_do_update(
                index_elements=["uuid"],  # 冲突检测字段
                set_={
                    "session_name": stmt.excluded.session_name,
                    "conversation": stmt.excluded.conversation,
                    "in_use": stmt.excluded.in_use,
                    "timestamp": stmt.excluded.timestamp,
                },
            )
            # 添加 RETURNING 子句
            returning_clause = [
                ConversationSchema.uuid,
                case(
                    (literal_column("changes()") == 0, "no_change"),
                    (literal_column("last_insert_rowid()") == 0, "updated"),
                    else_="created",
                ).label("operation"),
            ]
            final_stmt = update_stmt.returning(*returning_clause)
            result = await conn.execute(final_stmt)
            row = result.first()
            await conn.commit()
            return row.operation if row else False

    async def get_conversation(self, session_name: str) -> ConversationSchema | None:
        async with AsyncSession(self.engine) as conn:
            result = await conn.execute(
                select(ConversationSchema)
                .where(
                    (ConversationSchema.session_name == session_name)
                    & (ConversationSchema.in_use == True)
                )
                .order_by(ConversationSchema.timestamp)
                .limit(1)
            )
            item = result.scalar()
            # 会自动反序列化 conversation 字段
            return item

    async def get_in_use_conversations(self):
        """
        获取所有 in_use=True 的条目
        返回 ConversationSchema 对象列表（可能为空列表）
        """
        async with AsyncSession(self.engine) as conn:
            result = await conn.execute(
                select(ConversationSchema)
                .where(ConversationSchema.in_use.is_(True))
                .order_by(ConversationSchema.timestamp.desc())
            )
            return result.scalars().all()

    async def update_in_use_status(
        self, target_session_name: str, exclude_uuid: str
    ) -> int:
        """
        更新所有 session_name 等于目标值且 uuid 不等于排除值的条目的 in_use 为 False
        返回更新的条目数量
        """
        async with AsyncSession(self.engine) as session:
            try:
                # 构建更新语句
                stmt = (
                    update(ConversationSchema)
                    .where(
                        and_(
                            ConversationSchema.session_name == target_session_name,
                            ConversationSchema.uuid != exclude_uuid,
                        )
                    )
                    .values(in_use=False)
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount

            except Exception as e:
                # 发生错误时回滚
                await session.rollback()
                raise RuntimeError(f"更新失败: {str(e)}") from e

    async def del_item_unused(self) -> int:
        """
        删除所有 in_use 为 False 的条目
        返回被删除的行数
        """
        async with AsyncSession(self.engine) as conn:
            try:
                # 构建删除语句
                stmt = delete(ConversationSchema).where(
                    ConversationSchema.in_use.is_(False)
                )
                # 执行删除操作
                result = await conn.execute(stmt)
                await conn.commit()
                return result.rowcount
            except Exception as e:
                await conn.rollback()
                raise RuntimeError(f"删除操作失败: {str(e)}") from e


# if __name__ == "__main__":

#     async def main():
#         db = HistoryDataBase()
#         await db.initialize(os.path.join(os.path.dirname(__file__), "test.db"))

#         session_id = await db.create_session("test_session", Conversation(name="test"))
#         print(f"Created session: {session_id} {type(session_id)}")
#         loaded = await db.get_session(session_id)
#         print(f"Loaded conversation : {loaded.name} {type(loaded)}")

#     asyncio.run(main())
