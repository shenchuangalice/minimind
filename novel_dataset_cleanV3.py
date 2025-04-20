import os
import json
import re
from tqdm import tqdm
import chardet
from pathlib import Path

class NovelStructurer:
    def __init__(self, input_dir, output_dir):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.genre = self.input_dir.name
        self.config = {
            'title_pattern': r'^《(.+?)》|^【(.+?)】',
            'author_pattern': r'作者[：:]\s*([^\n]+?)(?:\n|$)',
            'volume_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+卷\s*.*?)\n',
            'chapter_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+[章回][^\n]*)(?:\n|$)',
            'outline_start': r'(?:内容简介|作品大纲)[：:\n]',
            'min_chapter_length': 200  # 章节最小内容长度（字符数）
        }

    def detect_encoding(self, file_path):
        with open(file_path, 'rb') as f:
            raw = f.read()
            return chardet.detect(raw)['encoding'] if chardet.detect(raw)['confidence'] > 0.75 else 'utf-8'

    def _process_content(self, raw_content):
        """内容清洗处理"""
        # 移除特殊空白字符
        cleaned = re.sub(r'[\x00-\x1F\x7F]+', '', raw_content)
        # 合并多余空行
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        # 移除行首空白
        cleaned = '\n'.join([line.strip() for line in cleaned.split('\n')])
        return cleaned.strip()

    def _process_single_file(self, file_path):
        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                text = f.read().replace('\ufeff', '')

                # 提取元数据
                meta = {
                    "genre": self.genre,
                    "title": (re.search(self.config['title_pattern'], text).group(1)
                            if re.search(self.config['title_pattern'], text)
                            else file_path.stem),
                    "author": (re.search(self.config['author_pattern'], text).group(1)
                            if re.search(self.config['author_pattern'], text)
                            else "未知"),
                    "outline": (re.search(f'{self.config["outline_start"]}(.+?)(?=\n{{2,}}|$)',
                                       text, re.DOTALL).group(1).strip()
                            if re.search(f'{self.config["outline_start"]}', text)
                            else ""),
                    "chapters": []
                }

                # 优化章节分割逻辑
                chapter_matches = list(re.finditer(self.config['chapter_pattern'], text))
                chapters = []

                # 处理章节前的内容
                if chapter_matches:
                    first_chapter_start = chapter_matches[0].start()
                    if first_chapter_start > 0:
                        preface = self._process_content(text[:first_chapter_start])
                        if len(preface) >= self.config['min_chapter_length']:
                            chapters.append({
                                "chapter_number": 0,
                                "chapter_title": "前言",
                                "content": preface
                            })

                # 构建章节结构
                for i, match in enumerate(chapter_matches):
                    chapter_title = match.group(1).strip()
                    start_pos = match.end()
                    end_pos = chapter_matches[i+1].start() if i+1 < len(chapter_matches) else len(text)
                    raw_content = text[start_pos:end_pos]

                    # 处理章节内容
                    processed_content = self._process_content(raw_content)
                    if len(processed_content) < self.config['min_chapter_length']:
                        continue

                    chapters.append({
                        "chapter_number": len(chapters) + 1,
                        "chapter_title": chapter_title,
                        "content": processed_content
                    })

                # 处理无章节的情况
                if not chapters:
                    full_content = self._process_content(text)
                    if len(full_content) >= self.config['min_chapter_length']:
                        chapters.append({
                            "chapter_number": 1,
                            "chapter_title": "全文",
                            "content": full_content
                        })

                meta["chapters"] = chapters
                return meta
        except Exception as e:
            print(f"处理失败 {file_path}: {str(e)}")
            return None

    def process_folder(self):
        structured_data = []
        txt_files = list(self.input_dir.glob("*.txt"))

        for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
            novel_data = self._process_single_file(file_path)
            if novel_data and novel_data["chapters"]:
                structured_data.append(novel_data)

        return structured_data

    def run(self):
        self.output_dir.mkdir(exist_ok=True, parents=True)
        output_file = self.output_dir / f"{self.genre}_structured.json"

        structured_data = self.process_folder()
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(structured_data, f, ensure_ascii=False, indent=2, sort_keys=True)

if __name__ == "__main__":
    input_base = "./raw_novels"
    output_dir = "./structured_data"

    genre_dirs = [d for d in Path(input_base).iterdir() if d.is_dir()]
    for genre_dir in tqdm(genre_dirs, desc="总进度"):
        processor = NovelStructurer(genre_dir, output_dir)
        processor.run()
