"""
新增「Discord Webhook」推送管道：不需要機器人，用頻道的 Webhook 網址發送，支援截圖縮圖。

同樣只在執行時把管道加進推送服務，不修改 src/ 下的任何檔案。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import requests

from one_dragon.base.push.push_channel import PushChannel
from one_dragon.base.push.push_channel_config import FieldTypeEnum, PushChannelConfigField
from one_dragon.base.push.push_service import PushService
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from cv2.typing import MatLike

CHANNEL_ID = 'DISCORD_WEBHOOK'

# Discord 卡片的字數上限
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
USERNAME_LIMIT = 80
TRUNCATED_SUFFIX = '…（已截斷）'

# 預設頭像：一條龍的應用圖示，放在本插件 GitHub 倉庫的 assets/avatar.png。
DEFAULT_AVATAR_URL = 'https://raw.githubusercontent.com/moonlight0XD/zzzod-discord-push/main/assets/avatar.png'
_PATCH_MARK = '_od_discord_webhook_patch_original_init'


class DiscordWebhook(PushChannel):

    def __init__(self) -> None:
        config_schema = [
            PushChannelConfigField(
                var_suffix='URL',
                title='Webhook 網址',
                icon='LINK',
                field_type=FieldTypeEnum.TEXT,
                placeholder='頻道設定 → 整合 → Webhook → 複製 Webhook 網址',
                required=True,
            ),
            PushChannelConfigField(
                var_suffix='USERNAME',
                title='顯示名稱',
                icon='PEOPLE',
                field_type=FieldTypeEnum.TEXT,
                placeholder='選填，留空則使用 Webhook 自己的名稱',
            ),
            PushChannelConfigField(
                var_suffix='AVATAR_URL',
                title='頭像網址',
                icon='PHOTO',
                field_type=FieldTypeEnum.TEXT,
                placeholder='選填，留空則使用一條龍的應用圖示',
            ),
        ]
        PushChannel.__init__(
            self,
            channel_id=CHANNEL_ID,
            channel_name='Discord Webhook',
            config_schema=config_schema,
        )

    def validate_config(self, config: dict[str, str]) -> tuple[bool, str]:
        url = config.get('URL', '').strip()
        if not url:
            return False, 'Webhook 網址不能為空'
        if not url.startswith('https://') or '/api/webhooks/' not in url:
            return False, 'Webhook 網址格式不正確，應以 https://discord.com/api/webhooks/ 開頭'
        return True, '設定驗證通過'

    def push(
        self,
        config: dict[str, str],
        title: str,
        content: str,
        image: MatLike | None = None,
        proxy_url: str | None = None,
    ) -> tuple[bool, str]:
        try:
            ok, msg = self.validate_config(config)
            if not ok:
                return False, msg

            url = config.get('URL', '').strip()
            proxies = self.get_proxy(proxy_url)

            image_data = self.image_to_bytes(image) if image is not None else None
            embed: dict = {
                'title': _truncate(title, TITLE_LIMIT),
                'description': _truncate(content, DESCRIPTION_LIMIT),
            }
            if image_data is not None:
                embed['thumbnail'] = {'url': 'attachment://screenshot.jpg'}
            payload: dict = {'embeds': [embed]}

            username = config.get('USERNAME', '').strip()
            if username:
                payload['username'] = username[:USERNAME_LIMIT]
            payload['avatar_url'] = config.get('AVATAR_URL', '').strip() or DEFAULT_AVATAR_URL

            response = self._send(url, payload, image_data, proxies)
            if response.status_code == 429:
                # 發太快被 Discord 限流：照它給的等待時間等一下，再重送一次
                time.sleep(_retry_after_seconds(response))
                response = self._send(url, payload, image_data, proxies)
                if response.status_code == 429:
                    return False, 'Discord Webhook 推送失敗(429)：發送太頻繁，請稍後再試'

            if response.status_code in (401, 404):
                return False, f'Discord Webhook 推送失敗({response.status_code})：Webhook 網址無效或已被刪除'
            response.raise_for_status()
            return True, '推送成功'
        except Exception as e:
            log.error('Discord Webhook 推送異常', exc_info=True)
            return False, f'Discord Webhook 推送異常: {str(e)}'

    @staticmethod
    def _send(url: str, payload: dict, image_data, proxies) -> requests.Response:
        headers = {'User-Agent': 'OneDragon'}
        if image_data is not None:
            image_data.seek(0)
            return requests.post(
                url,
                headers=headers,
                data={'payload_json': json.dumps(payload, ensure_ascii=False)},
                files={'files[0]': ('screenshot.jpg', image_data, 'image/jpeg')},
                proxies=proxies,
                timeout=30,
            )
        headers['Content-Type'] = 'application/json'
        return requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            proxies=proxies,
            timeout=30,
        )


def _truncate(text: str, limit: int) -> str:
    """超過 Discord 上限時截短，避免整則通知被拒收。"""
    text = text or ''
    if len(text) <= limit:
        return text
    return text[:limit - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX


def _retry_after_seconds(response: requests.Response) -> float:
    """讀取 Discord 429 回應要求的等待秒數，限制在 0.5～10 秒之間。"""
    seconds = 2.0
    try:
        seconds = float(response.json()['retry_after'])
    except Exception:
        try:
            seconds = float(response.headers.get('Retry-After', seconds))
        except (TypeError, ValueError):
            pass
    return min(max(seconds, 0.5), 10.0)


def _has_channel(service: PushService) -> bool:
    return CHANNEL_ID in getattr(service, '_id_2_channels', {})


def _patched_init_push_channels(self: PushService) -> None:
    original = getattr(PushService, _PATCH_MARK)
    original(self)
    if self._inited and not _has_channel(self):
        self._add_channel(DiscordWebhook())


def apply_patch(ctx=None) -> None:
    """讓推送服務在建立管道時多加一個 Discord Webhook；可重複呼叫。"""
    if not hasattr(PushService, _PATCH_MARK):
        setattr(PushService, _PATCH_MARK, PushService.init_push_channels)
    PushService.init_push_channels = _patched_init_push_channels

    # 推送服務若已經先初始化，直接補上
    service = getattr(ctx, 'push_service', None) if ctx is not None else None
    if isinstance(service, PushService) and service._inited and not _has_channel(service):
        service._add_channel(DiscordWebhook())
