# Flowerie API 总索引（v2.0.1）—— 唯一事实来源

> 表 = 权威 API 索引（方法/作用/权限/详解章节）；端点名（OneBot）不出现在此表。
> 语义层与开发者只见方法——低耦合红线。

| 方法 | 作用 | 权限 | 详解 |
| --- | --- | --- | --- |
**消息**
| `send_message(payload)` |  | `"send_message"` | [sdk.md](sdk.md) |
| `send_private_message(payload)` |  | `"send_message"` | [sdk.md](sdk.md) |
| `send_reply(payload)` |  | `"send_message"` | [sdk.md](sdk.md) |
| `delete_message(payload)` |  | `"delete_message"` | [sdk.md](sdk.md) |
| `get_message(payload)` |  | `"read_message_history"` | [sdk.md](sdk.md) |
| `get_group_history(payload)` |  | `"read_message_history"` | [sdk.md](sdk.md) |
| `get_context(payload)` |  | `"read_message_history"` | [sdk.md](sdk.md) |
**群信息/成员**
| `get_group(payload)` |  | `"read_group_info"` | [sdk.md](sdk.md) |
| `get_user(payload)` |  | `"read_user_info"` | [sdk.md](sdk.md) |
| `get_group_member(payload)` |  | `"read_group_info"` | [sdk.md](sdk.md) |
| `group_ban(payload)` |  | `"group_manage"` | [sdk.md](sdk.md) |
| `group_kick(payload)` |  | `"group_manage"` | [sdk.md](sdk.md) |
| `is_group_admin(payload)` |  | `"read_group_info"` | [sdk.md](sdk.md) |
| `is_group_owner(payload)` |  | `"read_group_info"` | [sdk.md](sdk.md) |
**社交**
| `tap(group_id,user_id)` | 群内戳一戳。 | `"read_group_info"` | [sdk.md](sdk.md) |
| `react(message_id,react_type)` | 消息表情回应（NapCat/Lagrange 自动适配）。 | `"read_message"` | [sdk.md](sdk.md) |
| `user_poke(user_id)` | 私聊戳一戳。 | `"read_user_info"` | [sdk.md](sdk.md) |
| `user_history(user_id,count)` | 好友/私聊消息历史。 | `"read_user_info"` | [sdk.md](sdk.md) |
**群管理**
| `group_portrait(group_id,file)` | 修改群头像。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_notice_delete(group_id,notice_id)` | 删除群公告。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_folder_create(group_id,name)` | 创建群文件文件夹。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_folder_delete(group_id,folder_id)` | 删除群文件文件夹。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_folder_rename(group_id,folder_id,name)` | 重命名群文件文件夹。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_file_delete(group_id,file_id,busid)` | 删除群文件。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_file_move(group_id,file_id,busid,target_folder_id)` | 移动群文件。 | `"group_manage"` | [sdk.md](sdk.md) |
| `group_forward(group_id,messages)` | 群合并转发。 | `"group_manage"` | [sdk.md](sdk.md) |
| `essence_list(group_id)` | 群精华消息列表。 | `"read_group_info"` | [sdk.md](sdk.md) |
| `group_honor(group_id,honor_type)` | 群荣誉信息。 | `"read_group_info"` | [sdk.md](sdk.md) |
**用户/系统**
| `user_forward(user_id,messages)` | 私聊合并转发。 | `"read_user_info"` | [sdk.md](sdk.md) |
| `group_info(group_id,no_cache)` | 群信息。 | `"read_group_info"` | [sdk.md](sdk.md) |
| `group_list(no_cache)` | 群列表。 | `"read_group_info"` | [sdk.md](sdk.md) |
| `handle_friend_request(flag,approve,remark)` |  | `"request_handle"` | [sdk.md](sdk.md) |
| `handle_group_request(flag,approve,reason)` |  | `"request_handle"` | [sdk.md](sdk.md) |
**数据/扩展**
| `kv_get(key)` |  | `"storage"` | [sdk.md](sdk.md) |
| `kv_set(key,value)` |  | `"storage"` | [sdk.md](sdk.md) |
| `kv_delete(key)` |  | `"storage"` | [sdk.md](sdk.md) |
| `kv_list()` |  | `"storage"` | [sdk.md](sdk.md) |
| `ai_chat(message,system)` |  | `"ai_chat"` | [sdk.md](sdk.md) |
| `mem_update(user_id,group_id,key,value)` |  | `"read_memory"` | [sdk.md](sdk.md) |
| `mem_clear(user_id,group_id)` |  | `"read_memory"` | [sdk.md](sdk.md) |
| `http_request(payload)` |  | `"http_request"` | [sdk.md](sdk.md) |
| `http_put(payload)` |  | `"http_request"` | [sdk.md](sdk.md) |
| `http_delete(payload)` |  | `"http_request"` | [sdk.md](sdk.md) |
| `http_head(payload)` |  | `"http_request"` | [sdk.md](sdk.md) |
| `matcher_register(matchers)` | 批量注册 Matcher（SDK 启动时调用；返回注册摘要）。 | `"read_message"` | [sdk.md](sdk.md) |
| `schedule_register(kind,when,name)` |  | `"scheduler"` | [sdk.md](sdk.md) |
| `schedule_cancel(schedule_id)` |  | `"scheduler"` | [sdk.md](sdk.md) |
| `schedule_list()` |  | `"scheduler"` | [sdk.md](sdk.md) |
| `log(level,message)` |  | `None` | [sdk.md](sdk.md) |
| `random_choice(choices)` |  | `None` | [sdk.md](sdk.md) |
| `random_int(low,high)` |  | `None` | [sdk.md](sdk.md) |
| `now()` |  | `None` | [sdk.md](sdk.md) |
| `format_time(timestamp,fmt)` |  | `None` | [sdk.md](sdk.md) |
