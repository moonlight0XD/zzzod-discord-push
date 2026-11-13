"""
新增「Discord Webhook」推送管道：不需要機器人，用頻道的 Webhook 網址發送，支援截圖縮圖。

同樣只在執行時把管道加進推送服務，不修改 src/ 下的任何檔案。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import TYPE_CHECKING

import requests

from one_dragon.base.push.push_channel import PushChannel
from one_dragon.base.push.push_channel_config import FieldTypeEnum, PushChannelConfigField
from one_dragon.base.push.push_service import PushService
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from cv2.typing import MatLike

CHANNEL_ID = 'DISCORD_WEBHOOK'

# 只接受 Discord 官方網域
ALLOWED_WEBHOOK_HOSTS = frozenset({
    'discord.com', 'ptb.discord.com', 'canary.discord.com',
    'discordapp.com', 'ptb.discordapp.com', 'canary.discordapp.com',
})
_WEBHOOK_PATH = re.compile(r'/api(?:/v\d+)?/webhooks/\d+/[\w-]+/?')
_WEBHOOK_URL_IN_TEXT = re.compile(r'(/webhooks/\d+/)[\w-]+')

# Discord 卡片的字數上限
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
USERNAME_LIMIT = 80
TRUNCATED_SUFFIX = '…（已截斷）'

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
                placeholder='選填，留空則使用 Webhook 自己的頭像',
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
        if not _is_discord_webhook_url(url):
            return False, 'Webhook 網址格式不正確，只接受 Discord 官方網址：https://discord.com/api/webhooks/…'
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
            avatar_url = config.get('AVATAR_URL', '').strip()
            if avatar_url:
                payload['avatar_url'] = avatar_url

            response = self._send(url, payload, image_data, proxies)
            if response.status_code == 429:
                # 發太快被 Discord 限流：照它給的等待時間等一下，再重送一次
                time.sleep(_retry_after_seconds(response))
                response = self._send(url, payload, image_data, proxies)
                if response.status_code == 429:
                    return False, 'Discord Webhook 推送失敗(429)：發送太頻繁，請稍後再試'

            # 只回報狀態碼，不使用 raise_for_status()：它的錯誤訊息會帶完整 Webhook 網址
            if response.status_code in (401, 404):
                return False, f'Discord Webhook 推送失敗({response.status_code})：Webhook 網址無效或已被刪除'
            if not 200 <= response.status_code < 300:
                return False, f'Discord Webhook 推送失敗(HTTP {response.status_code})'
            return True, '推送成功'
        except Exception as e:
            # Webhook 網址就是頻道的發文金鑰：例外訊息與 traceback 可能帶完整網址，
            # 所以不記錄 traceback、不回傳 str(e)，只留例外類型；萬一還有網址也打碼。
            reason = _mask_webhook_urls(type(e).__name__)
            log.error(f'Discord Webhook 推送異常：{reason}')
            return False, f'Discord Webhook 推送異常：{reason}'

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


def _is_discord_webhook_url(url: str) -> bool:
    """只接受 Discord 官方網域的 Webhook 網址，避免通知和截圖被送到其他伺服器。"""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == 'https'
        and (parsed.hostname or '') in ALLOWED_WEBHOOK_HOSTS
        and parsed.port is None
        and parsed.username is None
        and _WEBHOOK_PATH.fullmatch(parsed.path) is not None
    )


def _mask_webhook_urls(text: str) -> str:
    """把文字中的 Webhook 金鑰打碼。"""
    return _WEBHOOK_URL_IN_TEXT.sub(r'\1***', text)


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
