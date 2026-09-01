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
| `group_admins(payload)` | 群管理员列表（成员列表本地过滤 admin/owner） | `read_group_info` |
| `group_apply(payload)` | 群申请处理（等价 handle_group_request） | `request_handle` |
| `group_ban(payload)` |  | `group_manage` |
| `group_essence(payload)` | 群精华消息列表（等价 essence_list） | `read_group_info` |
| `group_file_delete(payload)` | 删除群文件。 | `group_manage` |
| `group_file_move(payload)` | 移动群文件。 | `group_manage` |
| `group_file_rename(payload)` | 重命名群文件（v1 无端点→not supported） | `group_manage` |
| `group_file_upload(payload)` | 上传群文件（v1 无专用端点→not supported） | `group_manage` |
| `group_folder_create(payload)` | 创建群文件文件夹。 | `group_manage` |
| `group_folder_delete(payload)` | 删除群文件文件夹。 | `group_manage` |
| `group_folder_rename(payload)` | 重命名群文件文件夹。 | `group_manage` |
| `group_forward(payload)` | 群合并转发。 | `group_manage` |
| `group_honor(payload)` | 群荣誉信息。 | `read_group_info` |
| `group_info(payload)` | 群信息。 | `read_group_info` |
| `group_invite(payload)` | 群邀请（v1 无端点→not supported） | `group_manage` |
| `group_kick(payload)` |  | `group_manage` |
| `group_list(payload)` | 群列表。 | `read_group_info` |
| `group_member_search(payload)` | 群成员搜索（group_id + query；成员列表本地过滤） | `read_group_info` |
| `group_member_update(payload)` | 群成员信息更新（user_id + card；等价设置群名片） | `group_manage` |
| `group_mute_status(payload)` | 群成员禁言状态（v1 无查询端点→not supported） | `read_group_info` |
| `group_notice_create(payload)` | 创建群公告（等价发送公告） | `group_manage` |
| `group_notice_delete(payload)` | 删除群公告。 | `group_manage` |
| `group_notice_update(payload)` | 更新群公告（删除旧公告+发送新公告组合） | `group_manage` |
| `group_portrait(payload)` | 修改群头像。 | `group_manage` |
| `group_title(payload)` | 群成员头衔（group_id/user_id/title；等价 set_group_special_title） | `group_manage` |
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
| `emoji(payload)` | Emoji 回应（message_id + emoji；等价反应） | `send_message` |
| `emoji_list(payload)` | 表情回应列表（v1 无查询端点→not supported） | `read_message_history` |
| `essence_list(payload)` | 群精华消息列表。 | `read_group_info` |
| `like(payload)` | 点赞（user_id；等价点赞好友资料） | `send_message` |
| `poke(payload)` | 戳一戳（user_id→好友戳；group_id+user_id→群戳，群戳 v1 无端点） | `send_message` |
| `react(payload)` | 消息表情回应（NapCat/Lagrange 自动适配）。 | `read_message` |
| `reaction(payload)` | 表情回应（message_id + react_type；等价 react） | `send_message` |
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
| `memory_delete(payload)` | 记忆删除（插件 KV 域删除） | `write_memory` |
| `memory_expire(payload)` | 记忆过期查询（v1 无 TTL 域→not supported） | `read_memory` |
| `memory_get(payload)` | 记忆读取（等价 get_memory） | `read_memory` |
| `memory_pin(payload)` | 记忆置顶（v1 花语无置顶域→not supported） | `write_memory` |
| `memory_search(payload)` | 语义记忆检索（花语记忆；相似度召回，返回回忆文本） | `read_memory` |
| `memory_semantic(payload)` | 语义检索（等价 memory_search） | `read_memory` |
| `memory_tag(payload)` | 记忆标签（插件 KV 域 tag: 前缀） | `storage` |
| `memory_update(payload)` | 记忆更新（等价 write_memory） | `write_memory` |

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
| `ai_budget(payload)` | 预算/限额（配置的每日限额与剩余） | `ai_chat` |
| `ai_chat(payload)` |  | `ai_chat` |
| `ai_embedding(payload)` | AI 向量化（文本→向量；复用花语向量模型客户端） | `ai_chat` |
| `ai_model_info(payload)` | 模型信息（名称/地址/类型） | `ai_chat` |
| `ai_models(payload)` | 模型列表（已配置 AI 模型） | `ai_chat` |
| `ai_rerank(payload)` | AI 重排（query+documents→相关性得分） | `ai_chat` |
| `ai_stream(payload)` | AI 流式对话（收集 chunks 返回；主进程流式请求） | `ai_chat` |
| `ai_token(payload)` | Token 统计（文本→token 估算） | `ai_chat` |
| `ai_usage(payload)` | 用量统计（调用次数/费用指标） | `ai_chat` |
| `ai_vision(payload)` | AI 视觉识图（图片地址/描述；主进程 vision 客户端，敏感图不可见跳转） | `ai_chat` |
| `http_delete(payload)` |  | `http_request` |
| `http_download(payload)` |  | `http_request` |
| `http_head(payload)` |  | `http_request` |
| `http_put(payload)` |  | `http_request` |
| `http_request(payload)` |  | `http_request` |
| `mcp_call(payload)` | MCP 工具调用（管理员配置服务器；工具白名单） | `http_request` |
| `mcp_prompt(payload)` | MCP Prompt 模板（v1 未实现→not supported） | `http_request` |
| `mcp_resource(payload)` | MCP 资源读取（v1 未实现→not supported） | `http_request` |
| `mcp_server(payload)` | MCP 服务器列表（已配置；含测试状态） | `http_request` |
| `mcp_status(payload)` | MCP 服务器状态（在线探测） | `http_request` |
| `mcp_tools(payload)` | MCP 工具列表（配置声明与在线工具） | `http_request` |

**其他**
| 方法 | 作用 | 权限 |
| --- | --- | --- |
| `__init__(payload)` |  | `—` |
| `audio_info(payload)` | 音频信息（大小/格式；时长需网关辅助） | `filesystem_read` |
| `call(payload)` | 通用语义化动作调用（v1.5；封装唯一，动作名白名单由主进程校验）。 | `—` |
| `edit_message(payload)` | 编辑消息（网关需支持；不支持时返回 not supported in v1） | `delete_message` |
| `favorite_message(payload)` | 收藏消息（网关需支持；当前 v1 无端点→not supported） | `read_message_history` |
| `file_convert(payload)` | 文件转换（v1 无转换器→not supported） | `filesystem_read` |
| `file_delete(payload)` | 删除插件空间文件 | `filesystem_write` |
| `file_download(payload)` | 文件下载（仅插件空间） | `filesystem_read` |
| `file_info(payload)` | 文件信息（大小/类型/图片尺寸；插件空间） | `filesystem_read` |
| `file_upload(payload)` | 文件上传到插件 WebUI 空间（web_ui.files 权限；安全校验） | `filesystem_write` |
| `format_time(payload)` |  | `—` |
| `forward_message(payload)` | 转发消息（payload 含 group_id/user_id + message_id；自动选群/私聊） | `send_message` |
| `get_group(payload)` |  | `read_group_info` |
| `get_group_info(payload)` |  | `read_group_info` |
| `get_group_member(payload)` |  | `read_group_info` |
| `get_group_members(payload)` |  | `read_group_info` |
| `get_memory(payload)` |  | `read_memory` |
| `handle_friend_request(payload)` |  | `request_handle` |
| `handle_group_request(payload)` |  | `request_handle` |
| `image_compress(payload)` | 图片压缩（v1 无图像库→not supported） | `filesystem_read` |
| `image_resize(payload)` | 图片缩放（v1 无图像库→not supported） | `filesystem_read` |
| `image_screenshot(payload)` | 图片截图（v1 无图像能力→not supported） | `filesystem_read` |
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
| `video_info(payload)` | 视频信息（大小/格式；时长需网关辅助） | `filesystem_read` |
| `write_memory(payload)` |  | `write_memory` |
