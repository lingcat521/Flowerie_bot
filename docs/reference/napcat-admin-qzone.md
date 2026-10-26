# NapCat 群管理 / QQ空间 动作对照（v2.10 逆向参考）

> 来源：NapCat v4.18.41 产物实测（`NapCat.Shell/napcat.mjs`）+ 官方文档缺口盘点。
> 本文只记录**接口事实**（OneBot 动作名 / 参数 / 返回 / 底层实现），供 Flowerie 适配层与 SDK 对照。

## 群管理员

| OneBot 动作 | 参数 | 返回 | NapCat 底层 |
| --- | --- | --- | --- |
| `set_group_admin` | group_id, user_id, enable(bool/str) | null | 先 `getUidByUinV2` 转 UID → NT `modifyMemberRole(group, uid, KADMIN/KMEMBER)` |
| `set_group_ban` | group_id, user_id, duration(秒,0=解除) | null | 角色校验（群主不可禁；禁管理员需自己是群主）→ NT `setMemberShutUp(group, [{uid, timeStamp}])` |
| `set_group_kick` | group_id, user_id, reject_add_request | null | NT `kickMember(group, [uid], reject, '')` |
| `set_group_whole_ban` | group_id, enable | null | NT `setGroupShutUp` |
| `set_group_card` | group_id, user_id, card | null | NT `modifyMemberCardName` |
| `set_group_name` | group_id, group_name | null | NT `modifyGroupName` |
| `set_group_leave` | group_id, is_dismiss | null | NT `quitGroup`（群主 + is_dismiss=解散） |
| `set_group_special_title` | group_id, user_id, special_title | null | **oidb 直发**：cmd 2300 sub 2，protobuf `{groupUin, body:{targetUid, specialTitle, expiredTime:-1, uinName}}` |
| `get_group_shut_list` | group_id | 禁言成员数组 | NT `getGroupShutUpMemberList` |

**NTGroupMemberRole 枚举**：0 未指定 / 1 陌生人 / 2 普通成员 / **3 管理员** / **4 群主**。

**管理员变动事件**：MsgPush 的 `contentHead.type === 44` → protobuf `GroupAdmin{groupUin, flag, isPromote, body{extraEnable|extraDisable{adminUid, isPromote}}}`；
上报为 `notice_type=group_admin, sub_type=set|unset`。**不走**群通知列表（`onGroupNotifiesUpdated` 显式排除了 SET_ADMIN / CANCEL_ADMIN_*）。

## QQ空间

| OneBot 动作 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `send_qzone_msg` | content, images[](file:// http(s):// base64://), ugc_right, target_uins[] | `{tid}` | 图片逐张上传后拼 richval |
| `delete_qzone_msg` | tid | null | 按 tid 删除 |

**ugc_right**：1 所有人 / 4 好友 / 16 部分好友可见 / 64 仅自己 / 128 部分好友不可见（16、128 必须带 target_uins）。

**认证链**：`forceFetchClientKey()` → `https://ssl.ptlogin2.qq.com/jump?...` 取 skey →
`getTipOffService().getPskey(['qzone.qq.com'], true)` 取 pskey →
`g_tk = djb2(skey) & 0x7FFFFFFF`（`hash = hash + (hash << 5) + charCode`）→
cookie `p_uin=o{uin}; p_skey={pskey}; skey={skey}; uin=o{uin}`。

**上传图片**：POST `https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk=...`
表单关键字段：`uin/skey/p_skey/p_uin/uploadtype=1/albumtype=7/refer=shuoshuo/output_type=jsonhtml/base64=1/picfile=<base64>/hd_width=2048/hd_height=10000/hd_quality=96`。
响应是 `frameElement.callback({...});</script>` 包裹的 JSON；richval = `",{albumid},{lloc},{lloc},{type},{h},{w},,{h},{w}"`，多图用 `\t` 连接。

**Flowerie 侧**：图片参数接受本地绝对路径（`/sdcard/a.jpg`、`~/a.jpg`），会归一化成 `file://` URI 再交给 NapCat（其上传器只认 URI）；相对路径直接拒绝。

**发说说**：POST `https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6?g_tk=...`
字段：`syn_tweet_verson=1/paramstr=1/con=<正文>/feedversion=1/ver=1/ugc_right/to_sign=0/hostuin/code_version=1/format=json/qzreferrer`；
带图加 `richtype=1 + richval`；16/128 加 `allow_uins=uin1|uin2 + who=1`。
返回 `{subcode|code, tid|t1_tid}`，成功取 `t1_tid || tid`。

**删说说**：POST `.../cgi-bin/emotion_cgi_delete_v6?g_tk=...`，字段 `hostuin/tid/t1_source=1/code_version=1/format=json/qzreferrer`。

## 文档缺口（实测发现）

- `delete_qzone_msg` 的 schema 描述称 tid 来自 `get_qzone_msg_list`，但 **v4.18.41 没有该动作**
  （枚举共 182 个动作，QQ空间只有 send/delete 两个）——tid 目前只能从发送返回值获得。
- `set_group_special_title` 是唯一"NapCat 自己组 protobuf 包"（oidb 2300/2）的群管操作，其余全部委托 QQ NT 原生
  `IGroupService`——所以 Windows/Linux 行为一致性由 QQ NT 版本决定。

## Flowerie 侧映射（v2.10）

- 服务层：`src/services/group_admin.py`（12 个操作）、`src/services/qzone.py`（发布/删除/本地历史）
- Adapter：`BotAdapter.set_group_admin / kick_with_reject / get_group_shut_list / quit_group / qzone_publish / qzone_delete`
- 插件 API：`group_shut_list / group_leave / qzone_publish / qzone_delete`（权限 `read_group_info` / `group_manage` / `qzone`）
- Web UI：`群管理` / `QQ空间` 两个页签（零 JS 表单）
