# Flowerie API 总索引（自动生成·唯一事实来源）

> 由 scripts/gen_api_md.py 生成（AST from PluginApi）；端点名（OneBot）不出现在此。
> 语义方法若网关无对应端点，运行时返回 `not supported in v1`（绝不静默）。


**消息**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `delete_message(payload)` |  | `delete_message` |
| `get_context(payload)` |  | `read_message_history` |
| `get_group_history(payload)` |  | `read_message_history` |
| `get_message(payload)` |  | `read_message_history` |
| `send_message(payload)` |  | `send_message` |
| `send_private_message(payload)` |  | `send_message` |
| `send_reply(payload)` |  | `send_message` |

**群**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `group_admin(payload)` |  | `group_manage` |
| `group_ban(payload)` |  | `group_manage` |
| `group_file_delete(payload)` | 删除群文件。 | `group_manage` |
| `group_file_move(payload)` | 移动群文件。 | `group_manage` |
| `group_folder_create(payload)` | 创建群文件文件夹。 | `group_manage` |
| `group_folder_delete(payload)` | 删除群文件文件夹。 | `group_manage` |
| `group_folder_rename(payload)` | 重命名群文件文件夹。 | `group_manage` |
| `group_forward(payload)` | 群合并转发。 | `group_manage` |
| `group_honor(payload)` | 群荣誉信息。 | `read_group_info` |
| `group_info(payload)` | 群信息。 | `read_group_info` |
| `group_kick(payload)` |  | `group_manage` |
| `group_list(payload)` | 群列表。 | `read_group_info` |
| `group_notice_delete(payload)` | 删除群公告。 | `group_manage` |
| `group_portrait(payload)` | 修改群头像。 | `group_manage` |
| `is_group_admin(payload)` |  | `read_group_info` |
| `is_group_owner(payload)` |  | `read_group_info` |

**关系/用户**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `friend_category(payload)` | 好友分类（等价 friend_group；v1 无端点→not supported） | `read_user_info` |
| `friend_delete(payload)` | 删除好友（v1 无端点→not supported） | `read_user_info` |
| `friend_detail(payload)` | 好友详细信息（user_id；列表内匹配详情） | `read_user_info` |
| `friend_group(payload)` | 好友分组管理（v1 无端点→not supported） | `read_user_info` |
| `friend_online(payload)` | 好友在线状态（v1 无端点→not supported） | `read_user_info` |
| `friend_remark(payload)` | 设置好友备注（网关需支持；v1 无端点→not supported） | `read_user_info` |
| `get_user(payload)` |  | `read_user_info` |
| `user_forward(payload)` | 私聊合并转发。 | `read_user_info` |
| `user_history(payload)` | 好友/私聊消息历史。 | `read_user_info` |
| `user_poke(payload)` | 私聊戳一戳。 | `read_user_info` |

**社交互动**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `essence_list(payload)` | 群精华消息列表。 | `read_group_info` |
| `react(payload)` | 消息表情回应（NapCat/Lagrange 自动适配）。 | `read_message` |
| `tap(payload)` | 群内戳一戳。 | `read_group_info` |

**记忆/存储**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `kv_delete(payload)` |  | `storage` |
| `kv_get(payload)` |  | `storage` |
| `kv_list(payload)` |  | `storage` |
| `kv_set(payload)` |  | `storage` |
| `mem_clear(payload)` |  | `read_memory` |
| `mem_update(payload)` |  | `read_memory` |

**插件运行时**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `matcher_register(payload)` | 批量注册 Matcher（SDK 启动时调用；返回注册摘要）。 | `read_message` |
| `schedule_cancel(payload)` |  | `scheduler` |
| `schedule_list(payload)` |  | `scheduler` |
| `schedule_register(payload)` |  | `scheduler` |

**AI/MCP**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `ai_chat(payload)` |  | `ai_chat` |
| `http_delete(payload)` |  | `http_request` |
| `http_download(payload)` |  | `http_request` |
| `http_head(payload)` |  | `http_request` |
| `http_put(payload)` |  | `http_request` |
| `http_request(payload)` |  | `http_request` |

**其他**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `__init__(payload)` |  | `—` |
| `call(payload)` | 通用语义化动作调用（v1.5；封装唯一，动作名白名单由主进程校验）。 | `—` |
| `edit_message(payload)` | 编辑消息（网关需支持；不支持时返回 not supported in v1） | `delete_message` |
| `favorite_message(payload)` | 收藏消息（网关需支持；当前 v1 无端点→not supported） | `read_message_history` |
| `format_time(payload)` |  | `—` |
| `forward_message(payload)` | 转发消息（payload 含 group_id/user_id + message_id；自动选群/私聊） | `send_message` |
| `get_group(payload)` |  | `read_group_info` |
| `get_group_info(payload)` |  | `read_group_info` |
| `get_group_member(payload)` |  | `read_group_info` |
| `get_group_members(payload)` |  | `read_group_info` |
| `get_memory(payload)` |  | `read_memory` |
| `handle_friend_request(payload)` |  | `request_handle` |
| `handle_group_request(payload)` |  | `request_handle` |
| `log(payload)` |  | `—` |
| `mark_message(payload)` | 标记消息（已读/未读；v1 无端点→not supported） | `delete_message` |
| `merge_message(payload)` | 消息合并（payload 段列表 → 单条消息负载；纯本地语义） | `send_message` |
| `now(payload)` |  | `—` |
| `quote_chain(payload)` | 引用链解析（message_id 逐条回溯引用，≤3 层，纯本地语义） | `read_message_history` |
| `random_choice(payload)` |  | `—` |
| `random_int(payload)` |  | `—` |
| `read_status(payload)` | 消息已读状态查询（v1 无端点→not supported） | `read_message_history` |
| `search_message(payload)` | 消息搜索（user_id/group_id + query + count：拉取历史并在本地过滤） | `read_message_history` |
| `split_message(payload)` | 消息拆段（payload.text；按段/长度拆分，纯本地语义） | `read_message` |
| `write_memory(payload)` |  | `write_memory` |
