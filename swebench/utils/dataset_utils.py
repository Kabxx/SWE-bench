from datasets import Dataset, DatasetDict,load_dataset,concatenate_datasets
from huggingface_hub import HfApi, HfFolder, Repository
import json
import os

# dataset: list of json objects
# mutlti Json : each line is a json object
# json : a list of json objects
# List : a list of json objects

def multiJson2dataset(json_file_path):
    dataset = []
    with open(json_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:  # 跳过空行
                try:
                    data = json.loads(line)
                    dataset.append(data)
                except json.JSONDecodeError as e:
                    print(f"Failed to decode line: {line}\nError: {e}")
    return dataset

def json2dataset(json_file_path):
    
    pass


def List2dataset(json_file_path: str):
    """
    将 JSON 文件（整体是一个列表）转换为 Hugging Face Dataset 格式。
    
    Args:
        json_file_path (str): JSON 文件的路径。
        
    Returns:
        dataset (datasets.Dataset): 转换后的数据集。
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        try:
            # 直接读取整个 JSON 文件为一个列表
            data = json.load(f)
            # 确保 data 是一个包含字典的列表
            if isinstance(data, list) and all(isinstance(item, dict) for item in data):
                dataset = Dataset.from_list(data)
                return dataset
            else:
                raise ValueError("The JSON file does not contain a list of dictionaries.")
                
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON file: {json_file_path} - Error: {e}")
            raise


def List2json(input_file_path: str, output_file_path: str):
    """
    将 JSON 文件中的数据逐行写入 JSON 文件
    :param input_file_path: 输入的 JSON 文件路径
    :param output_file_path: 输出的 .json 文件路径
    """
    # 读取文件内容，假设文件是一个标准的 JSON 数组
    with open(input_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)  # 解析为 Python 列表
    
    # 将数据逐行写入 .jsonl 文件
    with open(output_file_path, "w", encoding="utf-8") as f_out:
        for item in data:
            f_out.write(json.dumps(item) + "\n")  # 将每个元素写为一行 JSON 对象


def upload_to_huggingface(dataset, dataset_name):
    """
    将数据集上传到 Hugging Face 数据集中心。
    
    Args:
        dataset (datasets.Dataset): 要上传的数据集。
        dataset_name (str): 数据集名称。
        token (str): Hugging Face 的 API token。
        
    Returns:
        None
    """
    hf_token = os.environ.get("HUGGING_FACE_HUB_TOKEN", None)
    # 设置 API Token
    HfFolder.save_token(hf_token)
    api = HfApi()
    
    # 保存数据集到本地并上传
    dataset.push_to_hub(dataset_name, token=hf_token)
    print(f"Dataset '{dataset_name}' uploaded successfully!")

if __name__ == "__main__":
    # 设置 JSON 文件路径、数据集名称和 Hugging Face API Token
    json_file_path = "/root/ARiSE/SWEbench/SWE-bench/swebench/versioning/results/arrow-rs-task-instances_versions.json"  # 替换为你的 JSON 文件路径
    dataset_name = "r1v3r/arrow-rs"  # 替换为你想要的数据集名称
    dataset_list = List2dataset(json_file_path)

    # huggingface_dataset = load_dataset('r1v3r/bitflags_validated_v2', split='train')

    # combined_dataset = concatenate_datasets([huggingface_dataset, dataset_list])

    # 将数据集上传到 Hugging Face 数据集中心
    upload_to_huggingface(dataset_list, dataset_name)