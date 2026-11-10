from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext

from . import const


class DiscordChannelPushApp(ZApplication):
    """佔位應用：本插件的功能在載入時就已生效，這個應用什麼都不做。"""

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=const.APP_ID,
            op_name=const.APP_NAME,
        )

    @operation_node(name='開始', is_start_node=True)
    def start(self) -> OperationRoundResult:
        return self.round_success()
