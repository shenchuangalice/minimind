import os
import json
import re
from tqdm import tqdm
import chardet
from pathlib import Path
import textwrap

class NovelDatasetGenerator:
    def __init__(self, input_dir, output_dir):
            self.input_dir = Path(input_dir)
            self.output_dir = Path(output_dir)
            self.genre = self.input_dir.name
            self.config = {
                'title_pattern': r'^(?:《)?([^》\n]{1,30})(?:》)?\s*作者[：:]',
                'author_pattern': r'作者[：:]\s*([^\n]+?)\s*\n',
                'chapter_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+[章回节][^\n]{1,50})',
                'outline_start': r'(?:内容简介|作品大纲)[：:]?\n',
                'min_content_length': 200,
                'chapter_summary_length': 100,
                'prompt_templates': {
                    'outline_request': "请生成【{genre}】类型的小说，小说的【主题大纲】是：{theme}，需要写出【{chapter_count}】章的长度，请给我每一章的小说章节大纲",
                    'content_request': "请根据我的小说章节大纲，帮我生成【{length}】字的小说章节内容：{outline}"
                }
            }

    def detect_encoding(self, file_path):
        with open(file_path, 'rb') as f:
            raw = f.read()
            return chardet.detect(raw)['encoding'] if chardet.detect(raw)['confidence'] > 0.75 else 'utf-8'

    def _build_dialogue_pair(self, prompt, content):
        return {
            "text": f"<s>{prompt}</s> <s>{content}</s>"
        }

    def _extract_summary(self, text):
            """更智能的摘要提取"""
            # 去除特殊符号和空白
            clean_text = re.sub(r'[　【】（）《》“”‘’…]', '', text.strip())
            # 找到第一个完整句子结尾
            sentence_end = re.search(r'[。！？…](?![^（）]*\))', clean_text)  # 排除括号内的标点
            if sentence_end:
                summary = clean_text[:sentence_end.end()]
                if len(summary) >= self.config['chapter_summary_length']:
                    return summary[:self.config['chapter_summary_length']] + '...'
                return summary
            return clean_text[:self.config['chapter_summary_length']] + '...'

    def _process_single_file(self, file_path):
            try:
                encoding = self.detect_encoding(file_path)
                with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                    text = f.read()

                    # 提取元数据
                    meta = {
                        "genre": self.genre,
                        "title": self._extract_title(text) or file_path.stem,
                        "theme": self._extract_theme(text),
                    }

                    # 分割章节
                    chapters = self._split_chapters(text)
                    if not chapters:
                        return []

                    # 生成样本
                    samples = []
                    samples.append(self._generate_outline_prompt(meta, chapters))
                    samples.extend(self._generate_content_prompts(meta, chapters))

                    return samples
            except Exception as e:
                print(f"处理失败 {file_path}: {str(e)}")
                return []
    def _extract_title(self, text):
            """增强标题提取"""
            match = re.search(self.config['title_pattern'], text)
            return match.group(1).strip() if match else None

    def _extract_author(self, text):
                """增强作者提取"""
                match = re.search(self.config['author_pattern'], text)
                return match.group(1).strip() if match else "未知作者"
    def _clean_title(self, title):
            """清洗标题中的冗余信息"""
            # 移除卷信息（示例："卷一 血色风云 第一章 美女盟主" → "美女盟主"）
            return re.sub(r'^第?[卷篇]\s*\S+\s+', '', title).strip()
    def _process_chapters(self, meta, chapters):
        samples = []
        for chapter_num, (title, content) in enumerate(chapters, 1):
            # 跳过空内容
            if not content.strip():
                continue

            # 生成大纲条目
            outline = f"{chapter_num} {self._clean_title(title)}:{self._extract_summary(content)}"

            # 生成大纲请求
            outline_prompt = self.config['prompt_templates']['outline_request'].format(
                genre=meta['genre'],
                theme=meta['theme'],
                chapter_count=len(chapters)
            )
            samples.append(self._build_dialogue_pair(outline_prompt, outline))

            # 生成内容请求
            paragraphs = [p for p in re.split(r'\n{2,}', content) if p.strip()]
            for para in paragraphs:
                content_prompt = self.config['prompt_templates']['content_request'].format(
                    length=len(para),
                    outline=self._extract_summary(para)
                )
                samples.append(self._build_dialogue_pair(content_prompt, para))

        return samples
    def _split_chapters(self, text):
        # 改进后的正则表达式，支持多种中文数字格式
        chapter_re = re.compile(
            r'(?:^|\n)(第[零一二三四五六七八九十百千万]+章)\s*[-—－~～]?\s*([^\n]{1,50})(?=\n|$)',
            re.MULTILINE
        )

        chapters = []
        matches = list(chapter_re.finditer(text))

        for i, match in enumerate(matches):
            raw_title = match.group(1)
            chapter_num = self._chinese_to_number(raw_title)  # 新增中文转数字方法
            clean_title = f"第{chapter_num}章 {match.group(2).strip()}"

            # 获取章节内容
            next_start = len(text) if i == len(matches)-1 else matches[i+1].start()
            content = text[match.end():next_start].strip()

            chapters.append((chapter_num, clean_title, content))  # 存储实际章节号

        return sorted(chapters, key=lambda x: x[0])
    def _chinese_to_number(self, chinese_str):
        # 完整的中文数字转换逻辑
        num_map = {
            '零':0, '一':1, '二':2, '三':3, '四':4, '五':5,
            '六':6, '七':7, '八':8, '九':9, '十':10,
            '百':100, '千':1000, '万':10000, '亿':100000000
        }

        total = 0
        current = 0
        for char in chinese_str:
            if char not in num_map:
                continue
            value = num_map[char]
            if value >= 10:
                if current == 0:
                    current = 1
                total += current * value
                current = 0
            else:
                current = current * 10 + value
        total += current
        return total
    def _num_to_chinese(self, num_str):
            """将数字编号转换为中文数字（用于过滤重复标题）"""
            num_map = {
                '1': '一', '2': '二', '3': '三', '4': '四', '5': '五',
                '6': '六', '7': '七', '8': '八', '9': '九', '10': '十'
            }
            return ''.join(num_map.get(c, c) for c in num_str if c.isdigit())
    def _normalize_chapter_title(self, title):
        """修复中文数字转换"""
        # 中文数字映射（支持到十万）
        num_map = {
            '零':0, '一':1, '二':2, '三':3, '四':4, '五':5,
            '六':6, '七':7, '八':8, '九':9, '十':10,
            '百':100, '千':1000, '万':10000
        }

        # 提取中文数字部分
        match = re.search(r'第([零一二三四五六七八九十百千万]+)章', title)
        if not match:
            return title

        ch_num = match.group(1)
        total = 0
        current = 0
        for c in ch_num:
            val = num_map.get(c, 0)
            if val >= 10:
                if current == 0:
                    current = 1
                total += current * val
                current = 0
            else:
                current = current * 10 + val
        total += current

        return f"第{total}章"
    def _extract_theme(self, text):
        """增强版主题提取方法"""
        # 改进后的正则表达式模式
        theme_pattern = re.compile(
            r'(?:内容简介|作品大纲)[：:]\n*'
            r'((?:.|\n)+?)'  # 匹配任意字符包括换行
            r'(?=\n{2,}(?:第[\d一二三四五六七八九十百千万零]+[卷部]|第[^\n]{1,20}章|正文\s*开始|[-=]{4,}|$))',
            flags=re.MULTILINE
        )

        # 预处理文本：合并多余的空白行
        clean_text = re.sub(r'\n{3,}', '\n\n', text)

        match = theme_pattern.search(clean_text)
        if not match:
            return self._fallback_theme_extract(clean_text)  # 备用提取方案

        theme_content = match.group(1).strip()

        # 后处理：清理引言中的章节提示
        theme_content = re.sub(r'\(第[^\n]+章\)', '', theme_content)  # 移除类似（第一章）的引用
        theme_content = re.sub(r'请看片花：\n', '', theme_content)   # 移除片花提示

        return textwrap.shorten(theme_content, 500, placeholder='...')
    def _fallback_theme_extract(self, text):
        """备用提取方案：提取前5个自然段"""
        paragraphs = []
        current_para = []

        for line in text.split('\n'):
            line = line.strip()
            if line:
                current_para.append(line)
            else:
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
                if len(paragraphs) >= 5:
                    break

        # 合并前5段（或实际存在的段落）
        return textwrap.shorten(' '.join(paragraphs[:5]), 500, placeholder='...')
    def _generate_outline_prompt(self, meta, chapters):
        outline_items = []
        for chapter_num, title, content in chapters:
            summary = self._extract_summary(content)
            outline_items.append(f"第{chapter_num}章 {title.split(' ',1)[-1]}: {summary}")

        return self._build_dialogue_pair(
            self.config['prompt_templates']['outline_request'].format(
                genre=meta['genre'],
                theme=meta['theme'],
                chapter_count=len(chapters)
            ),
            "\n".join(outline_items)
        )
    def _generate_content_prompts(self, meta, chapters):
        samples = []
        for chapter_num, title, content in chapters:
            outline = self._extract_summary(content)
            prompt = self.config['prompt_templates']['content_request'].format(
                length=len(content),
                outline=f"第{chapter_num}章 {outline}"
            )
            samples.append(self._build_dialogue_pair(prompt, content))
        return samples
    def _process_complete_chapter(self, samples, meta, current_content, all_outlines, current_title):
            """修复后的完整章节处理"""
            try:
                # 生成大纲请求
                if all_outlines:
                    outline_prompt = self.config['prompt_templates']['outline_request'].format(
                        genre=meta['genre'],
                        theme=meta['theme'],
                        chapter_count=len(all_outlines)
                    )
                    outline_response = "\n".join(all_outlines)
                    samples.append(self._build_dialogue_pair(outline_prompt, outline_response))

                # 生成内容请求
                full_content = '\n'.join(current_content).strip()
                if len(full_content) >= self.config['min_content_length']:
                    paragraphs = [p for p in re.split(r'\n{2,}', full_content) if p.strip()]
                    for para in paragraphs:
                        if all_outlines:
                            outline_part = all_outlines[0].split(':', 1)[-1].strip()
                        else:
                            outline_part = self._extract_summary(para)

                        content_prompt = self.config['prompt_templates']['content_request'].format(
                            length=len(para),
                            outline=outline_part
                        )
                        samples.append(self._build_dialogue_pair(content_prompt, para))
            except Exception as e:
                print(f"章节处理异常：{str(e)}")

    def process_folder(self):
        all_samples = []
        txt_files = list(self.input_dir.glob("*.txt"))
        for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
            all_samples.extend(self._process_single_file(file_path))
        return all_samples

    def run(self):
        self.output_dir.mkdir(exist_ok=True, parents=True)
        output_file = self.output_dir / f"{self.genre}_dataset.jsonl"

        samples = self.process_folder()
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in tqdm(samples, desc=f"写入 {self.genre} 数据"):
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    input_base = "./raw_novels"
    output_dir = "./structured_dataset"

    genre_dirs = [d for d in Path(input_base).iterdir() if d.is_dir()]
    for genre_dir in tqdm(genre_dirs, desc="处理总进度"):
        processor = NovelDatasetGenerator(genre_dir, output_dir)
        processor.run()
