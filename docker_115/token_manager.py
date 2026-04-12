import requests
import json
import hashlib
import base64
import secrets
import string
import qrcode_terminal # 需要安装此库：pip install qrcode-terminal
import time
import os

# 网络配置
REQUEST_TIMEOUT = 30       # 请求超时时间（秒）
MAX_RETRIES = 3            # 最大重试次数

# 配置
TOKEN_FILE = "token.txt"
AUTH_DEVICE_CODE_URL = "https://passportapi.115.com/open/authDeviceCode"
QRCODE_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
DEVICE_CODE_TO_TOKEN_URL = "https://passportapi.115.com/open/deviceCodeToToken"
REFRESH_TOKEN_URL = "https://passportapi.115.com/open/refreshToken" # 刷新令牌URL已恢复

# --- PKCE和令牌管理辅助函数 ---

def generate_code_verifier(length=128):
    """
    为PKCE code_verifier生成一个加密安全的随机字符串。
    长度将在43到128个字符（含）之间。
    """
    length = secrets.choice(range(43, 129))
    allowed_chars = string.ascii_letters + string.digits + '-._~'
    return ''.join(secrets.choice(allowed_chars) for _ in range(length))

def generate_code_challenge(code_verifier):
    """
    使用SHA256和Base64 URL安全编码从code_verifier生成PKCE code_challenge。
    """
    sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(sha256).rstrip(b'=').decode('ascii') # 使用urlsafe并移除填充

def read_token():
    """
    从token.txt文件中读取令牌数据。
    返回: 字典 或 None (如果文件未找到或格式无效)。
    """
    try:
        if not os.path.exists(TOKEN_FILE):
            print(f"令牌文件 '{TOKEN_FILE}' 未找到。")
            return None
        with open(TOKEN_FILE, "r", encoding='utf-8') as f:
            token_data = json.load(f)
            return token_data
    except json.JSONDecodeError:
        print(f"错误: 令牌文件 '{TOKEN_FILE}' 格式不是有效的JSON。")
        print("请检查文件内容。它应该是一个有效的JSON对象。")
        return None
    except Exception as e:
        print(f"读取令牌文件时发生意外错误: {e}")
        return None

def write_token(token_response_data: dict, api_status_code: int = 0):
    """
    将新的令牌数据以指定格式写入token.txt。
    参数:
        token_response_data (dict): 成功API响应的'data'部分（来自初始认证或刷新）。
        api_status_code (int): 原始API响应的'status'或'code'字段（0表示成功）。
    """
    access_token = token_response_data.get("access_token", "")
    refresh_token = token_response_data.get("refresh_token", "")
    expires_in = token_response_data.get("expires_in", 7200) # 如果未找到则默认为7200秒
    user_id = token_response_data.get("user_id", "") # 如果可用则包含user_id

    formatted_token_data = {
        "timestamp": int(time.time()),
        "state": 1, # 默认值或根据可用情况推导
        "code": api_status_code, # 使用API响应的实际状态/代码
        "message": "", # 如果可能则从API响应推导，否则为空
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "user_id": user_id # 存储user_id以方便使用
        },
        "error": "", # 如果可能则从API响应推导，否则为空
        "errno": api_status_code # 使用API响应的实际状态/代码
    }
    
    try:
        with open(TOKEN_FILE, "w", encoding='utf-8') as f:
            json.dump(formatted_token_data, f, indent=4, ensure_ascii=False)
        print(f"新令牌已保存到 '{TOKEN_FILE}'.")
    except Exception as e:
        print(f"写入新令牌到文件 '{TOKEN_FILE}' 时出错: {e}")

def is_token_expired(timestamp: int, expires_in: int) -> bool:
    """
    检查访问令牌是否过期或接近过期。
    包含60秒的缓冲时间以进行主动刷新。
    （此函数在当前主逻辑中不再直接用于触发刷新，但保留以供参考）
    """
    current_time = int(time.time())
    return (current_time - timestamp) > (expires_in - 60)

# --- API交互函数 ---

def get_initial_tokens_via_device_code(client_id: int):
    """
    执行115设备码认证流程以获取初始令牌。
    返回: 包含令牌数据的字典 (如果成功)，否则返回None。
    """
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    
    print("\n--- 启动设备码流程 ---")
    print("步骤1: 请求设备码...")
    auth_data = None
    try:
        response = requests.post(
            AUTH_DEVICE_CODE_URL,
            data={
                "client_id": client_id,
                "code_challenge": code_challenge,
                "code_challenge_method": "sha256"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status() # 对4xx或5xx响应抛出HTTPError
        auth_data = response.json()
        print(f"设备码响应状态: {response.status_code}")
        print(f"设备码响应JSON: {auth_data}")
    except requests.exceptions.RequestException as e:
        print(f"请求设备码时出错: {e}")
        if response is not None: print(f"原始响应: {response.text}")
        return None
    except json.JSONDecodeError:
        print(f"解析设备码响应时出错。原始数据: {response.text}")
        return None

    # 检查成功代码(0)和'data'是否存在
    if not auth_data or auth_data.get("code") != 0 or "data" not in auth_data:
        print(f"获取设备码失败。响应: {auth_data}")
        return None
    
    uid = auth_data['data'].get('uid')
    qrcode_content = auth_data['data'].get('qrcode')
    time_val = auth_data['data'].get('time')
    sign = auth_data['data'].get('sign')

    if not all([uid, qrcode_content, time_val, sign]):
        print("设备码响应缺少关键数据 (uid, qrcode, time, sign)。")
        return None

    print("\n步骤2: 请使用115客户端扫描下方显示的二维码:")
    qrcode_terminal.draw(qrcode_content)
    print(f"设备UID: {uid}")
    print(f"二维码内容: {qrcode_content}")

    print("\n步骤3: 正在轮询二维码状态...")
    while True:
        try:
            status_resp = requests.get(
                QRCODE_STATUS_URL,
                params={
                    "uid": uid,
                    "time": time_val,
                    "sign": sign
                },
                timeout=REQUEST_TIMEOUT
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            
            print(f"轮询状态响应: {status_data}")

            if status_data.get('data', {}).get('status') == 2: # 状态2: 已授权
                print("\n二维码已扫描并授权! 正在获取访问令牌...")
                break
            elif status_data.get('data', {}).get('status') == 1: # 状态1: 已扫描，等待确认
                print("二维码已扫描，等待用户确认...")
            else: # 状态0: 未扫描或其他状态
                print("二维码尚未扫描或用户操作待定...")
            
            time.sleep(5) # 每5秒轮询一次

        except requests.exceptions.RequestException as e:
            print(f"轮询二维码状态时出错: {e}")
            if status_resp is not None: print(f"原始响应: {status_resp.text}")
            time.sleep(3)  # 网络错误时等待3秒后继续轮询，而不是直接返回
            continue
        except json.JSONDecodeError:
            print(f"解析二维码状态响应时出错。原始数据: {status_resp.text}")
            return None
    
    print("\n步骤4: 正在将设备码换取访问令牌...")
    final_token_data = None
    try:
        token_resp = requests.post(
            DEVICE_CODE_TO_TOKEN_URL,
            data={
                "uid": uid,
                "code_verifier": code_verifier
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT
        )
        token_resp.raise_for_status()
        final_token_data = token_resp.json()
        print(f"最终令牌API响应: {final_token_data}")
    except requests.exceptions.RequestException as e:
        print(f"获取最终令牌时出错: {e}")
        if token_resp is not None: print(f"原始响应: {token_resp.text}")
        return None
    except json.JSONDecodeError:
        print(f"解析最终令牌响应时出错。原始数据: {token_resp.text}")
        return None

    # 检查成功代码(0)和'data'是否存在
    if final_token_data and final_token_data.get("code") == 0 and "data" in final_token_data:
        print("\n--- 初始令牌成功获取 ---")
        print(f"访问令牌: {final_token_data['data'].get('access_token')}")
        print(f"刷新令牌: {final_token_data['data'].get('refresh_token')}")
        print(f"有效期: {final_token_data['data'].get('expires_in')} 秒")
        print(f"用户ID: {final_token_data['data'].get('user_id')}")
        print("------------------------------------------")
        return final_token_data
    else:
        print(f"获取初始令牌失败。响应: {final_token_data}")
        return None

def refresh_existing_token(refresh_token_value: str):
    """
    使用refresh_token获取新的access_token。
    根据官方文档，此特定接口不需要client_id。
    带重试和指数退避机制。
    返回: 包含新令牌数据的字典 (如果成功)，否则返回None。
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "refresh_token": refresh_token_value
    }
    
    print("\n--- 尝试刷新令牌 ---")
    
    for attempt in range(MAX_RETRIES):
        response = None
        try:
            response = requests.post(REFRESH_TOKEN_URL, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
            print(f"刷新API响应状态码: {response.status_code}")
            response.raise_for_status() # 对4xx或5xx响应抛出HTTPError
            
            if not response.text or not response.text.strip(): # 检查空或只有空白字符的响应
                print(f"错误: 从 {REFRESH_TOKEN_URL} 收到空或只有空白字符的响应体，尽管状态码为 {response.status_code}。")
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    print(f"将在 {wait} 秒后重试 (第 {attempt + 2} 次)...")
                    time.sleep(wait)
                    continue
                return None
                
            result = response.json()
            print(f"刷新API响应JSON: {result}")

            # 根据您提供的日志，刷新API的成功判断应基于 'code' 字段。
            if result.get("code") == 0 and "data" in result:
                print("令牌刷新成功!")
                return result
            else:
                error_status = result.get('status', 'N/A') # 保留 status 作为错误信息的一部分
                error_code = result.get('code', 'N/A') # 获取 code 字段
                error_message = result.get('message', result.get('error', '未知错误'))
                print(f"刷新令牌失败: 状态 {error_status}, 代码 {error_code}, 消息: {error_message}")
                # API 返回明确错误（非网络问题），不重试
                return None
        except requests.exceptions.RequestException as e:
            print(f"刷新期间请求失败或网络错误 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if response is not None: print(f"原始响应: {response.text}")
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                print(f"将在 {wait} 秒后重试 (第 {attempt + 2} 次)...")
                time.sleep(wait)
            else:
                print(f"刷新令牌在 {MAX_RETRIES} 次尝试后仍失败")
                return None
        except json.JSONDecodeError:
            print(f"解析刷新API的JSON响应失败。")
            if response is not None: print(f"原始响应 (导致JSONDecodeError): >>>{response.text}<<<")
            return None
    
    return None

# --- 令牌管理核心逻辑 ---

def run_token_management_cycle(client_id: int):
    """
    执行一次令牌获取/刷新周期。
    """
    token_data = read_token()
    
    # 优先尝试刷新令牌
    if token_data and "data" in token_data and token_data["data"].get("refresh_token"):
        current_refresh_token_value = token_data["data"].get("refresh_token")
        print(f"检测到现有刷新令牌。尝试刷新...")
        
        new_token_response = refresh_existing_token(current_refresh_token_value)
        
        if new_token_response and new_token_response.get("code") == 0:
            write_token(new_token_response["data"], api_status_code=new_token_response.get("code", 0))
            print("通过令牌刷新认证成功。")
        else:
            print("令牌刷新失败（或刷新令牌无效）。回退到新的设备认证。")
            # 刷新失败时，进行设备码认证
            initial_token_response = get_initial_tokens_via_device_code(client_id)
            if initial_token_response:
                write_token(initial_token_response["data"], api_status_code=initial_token_response.get("code", 0))
                print("初始认证成功。")
            else:
                print("初始认证失败。无法获取令牌。")
    else:
        print("未找到现有令牌文件，或刷新令牌缺失/无效。正在启动新的设备认证。")
        # 没有现有令牌或刷新令牌时，直接进行设备码认证
        initial_token_response = get_initial_tokens_via_device_code(client_id)
        if initial_token_response:
            write_token(initial_token_response["data"], api_status_code=initial_token_response.get("code", 0))
            print("初始认证成功。")
        else:
            print("初始认证失败。无法获取令牌。")

# --- 主程序逻辑 ---

def main():
    #client_id = 156 # <<--- 重要: 请用你的实际CLIENT ID替换此值!
    client_id = 488948
    # 首次运行不等待，直接尝试获取/刷新令牌
    print(f"\n--- 脚本首次运行 ---")
    run_token_management_cycle(client_id)


if __name__ == "__main__":
    main()

