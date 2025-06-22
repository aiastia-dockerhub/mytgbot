async def check_admin(event, account_config):
    """Checks if the sender of the event is an admin (只检查当前账号的 admin_ids，类型统一为 int)"""
    admin_ids = account_config.get('admin_ids', [])
    # 统一 admin_ids 为 int 列表
    admin_ids_int = [int(i) for i in admin_ids]
    try:
        sender_id = int(event.sender_id)
    except Exception:
        sender_id = event.sender_id
    if sender_id in admin_ids_int:
        return True
    else:
        await event.respond("您不是管理员，无法使用此命令。")
        return False