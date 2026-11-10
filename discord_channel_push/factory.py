from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application.application_factory import ApplicationFactory
from one_dragon.base.operation.application_base import Application

from . import const
from .discord_webhook_channel import apply_patch

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext

# 插件被載入時立即生效（早於推送管道初始化）
apply_patch()


class DiscordChannelPushFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext):
        ApplicationFactory.__init__(self, const)
        self.ctx: ZContext = ctx
        apply_patch(ctx)

    def create_application(self, instance_idx: int, group_id: str) -> Application:
        from .app import DiscordChannelPushApp
        return DiscordChannelPushApp(self.ctx)
