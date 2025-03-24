import datetime
import typing
import uuid

import pydantic.v1 as pydantic
from sqlalchemy import BLOB, Boolean, Column, String, TypeDecorator
from sqlalchemy.orm import declarative_base

from pkg.core import entities as core_entities
from pkg.provider import entities as llm_entities
from pkg.provider.modelmgr import entities
from pkg.provider.sysprompt import entities as sysprompt_entities
from pkg.provider.tools import entities as tools_entities


class PydanticType(TypeDecorator):
    impl = BLOB

    def __init__(self, model_type: type[pydantic.BaseModel], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_type = model_type

    def process_bind_param(self, value: pydantic.BaseModel, dialect):
        if value is not None:
            # 根据 Pydantic 版本选择正确的方法
            if hasattr(value, "model_dump_json"):  # v2
                return value.model_dump_json().encode("utf-8")  # type: ignore
            else:  # v1
                return value.json().encode("utf-8")
        return None

    def process_result_value(self, value: bytes, dialect):
        if value is not None:
            # 根据 Pydantic 版本选择正确的方法
            if hasattr(self.model_type, "model_validate_json"):  # v2
                return self.model_type.model_validate_json(value.decode("utf-8"))  # type: ignore
            else:  # v1
                return self.model_type.parse_raw(value.decode("utf-8"))


Base = declarative_base()


class ConversationItem(pydantic.BaseModel):
    """对话，包含于 Session 中，一个 Session 可以有多个历史 Conversation，但只有一个当前使用的 Conversation"""

    prompt: sysprompt_entities.Prompt

    messages: list[llm_entities.Message]

    create_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    update_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    uuid: typing.Optional[str] = None
    """该对话的 uuid，在创建时不会自动生成。而是当使用 Dify API 等由外部管理对话信息的服务时，用于绑定外部的会话。具体如何使用，取决于 Runner。"""

    @classmethod
    def _from_conversation(cls, conversation: core_entities.Conversation):
        return cls(
            prompt=conversation.prompt,
            messages=conversation.messages,
            create_time=conversation.create_time,
            update_time=conversation.update_time,
            uuid=conversation.uuid,
        )

    def _to_conversation(
        self,
        use_model: entities.LLMModelInfo,
        use_funcs: list[tools_entities.LLMFunction] | None,
    ) -> core_entities.Conversation:
        return core_entities.Conversation(
            prompt=self.prompt,
            messages=self.messages,
            create_time=self.create_time,
            update_time=self.update_time,
            use_model=use_model,
            use_funcs=use_funcs,
            uuid=self.uuid,
        )


class ConversationSchema(Base):
    __tablename__ = "conversations"

    # conversation 的 uuid，条目的唯一标识
    uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_name = Column(String(255), nullable=False)
    in_use = Column(Boolean, default=False)
    conversation = Column(PydanticType(ConversationItem))
    timestamp = Column(String(255), nullable=False)
