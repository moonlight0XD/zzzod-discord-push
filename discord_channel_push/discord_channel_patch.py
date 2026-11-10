"""
給內建的「Discord 機器人」推送管道加上「頻道 ID」：

- 填了頻道 ID：機器人直接把訊息（含截圖縮圖）發到該伺服器頻道
- 沒填頻道 ID：保持原本的私訊行為

只在執行時替換 Discord 類別的方法，不修改 src/ 下的任何檔案，所以不影響自動更新。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import requests

from one_dragon.base.push.channel.discord import Discord
from one_dragon.base.push.push_channel_config import FieldTypeEnum, PushChannelConfigField
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from cv2.typing import MatLike

CHANNEL_ID_SUFFIX = 'CHANNEL_ID'
_PATCH_MARK = '_od_discord_channel_patch_originals'


def _channel_id_field() -> PushChannelConfigField:
    return PushChannelConfigField(
        var_suffix=CHANNEL_ID_SUFFIX,
        title='頻道 ID',
        icon='CHAT',
        field_type=FieldTypeEnum.TEXT,
        placeholder='（插件）填寫後發到此伺服器頻道，留空則私訊使用者',
        required=False,
    )


def _adjust_schema(channel: Discord) -> None:
    """在已有管道實例的欄位清單裡加上頻道 ID，使用者 ID 改為選填。原地修改，推送服務和設定頁共用同一個清單。"""
    schema = channel.config_schema
    for field in schema:
        if field.var_suffix == 'USER_ID':
            field.required = False
            field.placeholder = '私訊接收者的使用者 ID（填了頻道 ID 時可留空）'
    if not any(f.var_suffix == CHANNEL_ID_SUFFIX for f in schema):
        schema.append(_channel_id_field())


def _patched_init(self: Discord) -> None:
    originals = getattr(Discord, _PATCH_MARK)
    originals['__init__'](self)
    _adjust_schema(self)


def _patched_validate_config(self: Discord, config: dict[str, str]) -> tuple[bool, str]:
    if not config.get('BOT_TOKEN', '').strip():
        return False, '機器人 Token 不能為空'
    if not config.get('USER_ID', '').strip() and not config.get(CHANNEL_ID_SUFFIX, '').strip():
        return False, '使用者 ID 和頻道 ID 至少填寫一個'
    return True, '設定驗證通過'


def _patched_push(
    self: Discord,
    config: dict[str, str],
    title: str,
    content: str,
    image: MatLike | None = None,
    proxy_url: str | None = None,
) -> tuple[bool, str]:
    target_channel_id = config.get(CHANNEL_ID_SUFFIX, '').strip()
    if not target_channel_id:
        # 沒填頻道 ID，走原本的私訊邏輯
        originals = getattr(Discord, _PATCH_MARK)
        return originals['push'](self, config, title, content, image, proxy_url)

    try:
        ok, msg = self.validate_config(config)
        if not ok:
            return False, msg

        bot_token = config.get('BOT_TOKEN', '').strip()
        api_host = (config.get('API_HOST', '') or 'https://discord.com/api/v9').rstrip('/')
        proxies = self.get_proxy(proxy_url)
        headers = {
            'Authorization': f'Bot {bot_token}',
            'User-Agent': 'OneDragon',
        }
        message_url = f'{api_host}/channels/{target_channel_id}/messages'

        image_data = self.image_to_bytes(image) if image is not None else None
        if image_data is not None:
            image_data.seek(0)
            payload = self._build_message_payload(title, content, True)
            response = requests.post(
                message_url,
                headers=headers,
                data={'payload_json': json.dumps(payload, ensure_ascii=False)},
                files={'files[0]': ('screenshot.jpg', image_data, 'image/jpeg')},
                proxies=proxies,
                timeout=30,
            )
        else:
            headers['Content-Type'] = 'application/json'
            payload = self._build_message_payload(title, content)
            response = requests.post(
                message_url,
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                proxies=proxies,
                timeout=30,
            )

        if response.status_code == 403:
            return False, 'Discord 頻道推送被拒絕(403)：請確認機器人已加入該伺服器，並在頻道有「傳送訊息」「嵌入連結」「附加檔案」權限'
        if response.status_code == 404:
            return False, 'Discord 頻道推送失敗(404)：頻道 ID 不正確，或機器人看不到該頻道'
        response.raise_for_status()
        return True, '推送成功'
    except Exception as e:
        log.error('Discord 頻道推送異常', exc_info=True)
        return False, f'Discord 頻道推送異常: {str(e)}'


def apply_patch(ctx=None) -> None:
    """替換 Discord 的方法；可重複呼叫（插件熱重載時不會重複包裝）。"""
    if not hasattr(Discord, _PATCH_MARK):
        setattr(Discord, _PATCH_MARK, {
            '__init__': Discord.__init__,
            'push': Discord.push,
            'validate_config': Discord.validate_config,
        })

    Discord.__init__ = _patched_init
    Discord.push = _patched_push
    Discord.validate_config = _patched_validate_config

    # 推送管道若已經先建好，也補上欄位
    push_service = getattr(ctx, 'push_service', None) if ctx is not None else None
    for channel in getattr(push_service, 'channels', []) or []:
        if isinstance(channel, Discord):
            _adjust_schema(channel)

    log.info('Discord 頻道推送插件已啟用')
