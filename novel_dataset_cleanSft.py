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
                'max_sequence_length': 3000,
                'outline_chunk_size': 20,
                'context_paragraphs': 2,  # 保留前N个段落作为上下文
                'title_pattern': r'^(?:《)?([^》\n]{1,30})(?:》)?\s*作者[：:]',
                'chapter_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+[章回节][^\n]{1,50})',
                'min_content_length': 200,
                'chapter_summary_length': 100,
                'prompt_templates': {
                    'outline_request': "请生成【{genre}】类型的小说，小说的【主题大纲】是：{theme}，需要写出第{start}章到第{end}章（共{count}章）的小说章节大纲",
                    'content_request': "请根据第{chapter}章大纲（{outline}），帮我续写，前文内容：{context}"
                }
            }
    def _split_paragraphs(self, content):
            """智能段落分割"""
            paragraphs = []
            current_para = []

            for line in content.split('\n'):
                line = line.strip()
                if line:
                    current_para.append(line)
                else:
                    if current_para:
                        paragraphs.append(' '.join(current_para))
                        current_para = []
            if current_para:
                paragraphs.append(' '.join(current_para))
            return paragraphs
    def detect_encoding(self, file_path):
        with open(file_path, 'rb') as f:
            raw = f.read()
            return chardet.detect(raw)['encoding'] if chardet.detect(raw)['confidence'] > 0.75 else 'utf-8'

    def _build_dialogue_pair(self, prompt, content):
            """带格式的对话构建"""
            formatted_prompt = f"<s>{prompt}</s>"
            formatted_content = f"<s>{content}</s>"

            # 长度校验
            total_len = len(formatted_prompt) + len(formatted_content)
            if total_len > self.config['max_sequence_length']:
                available_len = self.config['max_sequence_length'] - len(formatted_prompt) - 10
                formatted_content = f"<s>{content[:available_len]}...</s>"

            return {
                "conversations": [
                    {"role": "user", "content": formatted_prompt},
                    {"role": "assistant", "content": formatted_content}
                ]
            }

    def _split_text(self, text, chunk_size):
        """智能文本分块"""
        chunks = []
        while len(text) > chunk_size:
            split_pos = text.rfind('\n', 0, chunk_size) or text.rfind('。', 0, chunk_size) or chunk_size
            chunks.append(text[:split_pos+1])
            text = text[split_pos+1:]
        if text:
            chunks.append(text)
        return chunks

    def _extract_summary(self, text):
        """改进的摘要提取"""
        clean_text = re.sub(r'[　【】（）《》“”‘’…]', '', text.strip())
        sentences = re.findall(r'[^。！？…]+[。！？…]?', clean_text)
        summary = []
        total_len = 0
        for sent in sentences:
            sent_len = len(sent)
            if total_len + sent_len > self.config['chapter_summary_length']:
                break
            summary.append(sent)
            total_len += sent_len
        return ''.join(summary) + ('...' if len(summary) < len(sentences) else '')

    def _process_single_file(self, file_path):
        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                text = f.read()

                meta = {
                    "genre": self.genre,
                    "title": self._extract_title(text) or file_path.stem,
                    "theme": self._extract_theme(text),
                }

                chapters = self._split_chapters(text)
                if not chapters:
                    return []

                samples = []
                samples.extend(self._generate_outline_prompts(meta, chapters))
                samples.extend(self._generate_content_prompts(meta, chapters))
                return samples
        except Exception as e:
            print(f"处理失败 {file_path}: {str(e)}")
            return []
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
    def _extract_title(self, text):
            """增强标题提取"""
            match = re.search(self.config['title_pattern'], text)
            return match.group(1).strip() if match else None
    def _split_chapters(self, text):
        """改进的章节分割"""
        chapter_re = re.compile(
            r'(?:^|\n)(第[零一二三四五六七八九十百千万]+章)\s*[-—－~～]?\s*([^\n]{1,50})(?=\n|$)',
            re.MULTILINE
        )
        chapters = []
        matches = list(chapter_re.finditer(text))

        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i+1].start() if i < len(matches)-1 else len(text)
            content = text[start:end].strip()
            chapters.append((
                self._chinese_to_number(match.group(1)),
                f"{match.group(1)} {match.group(2).strip()}",
                content
            ))
        return chapters
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
    def _generate_outline_prompts(self, meta, chapters):
        """分块生成大纲请求"""
        samples = []
        chunk_size = self.config['outline_chunk_size']
        for i in range(0, len(chapters), chunk_size):
            chunk = chapters[i:i+chunk_size]
            outline_items = []
            for chap in chunk:
                chapter_num, title, content = chap
                summary = self._extract_summary(content)
                outline_items.append(f"第{chapter_num}章 {title.split(' ',1)[-1]}: {summary}")

            prompt = self.config['prompt_templates']['outline_request'].format(
                genre=meta['genre'],
                theme=meta['theme'],
                start=i+1,
                end=i+len(chunk),
                count=len(chunk)
            )
            response = "\n".join(outline_items)
            samples.append(self._build_dialogue_pair(prompt, response))
        return samples

    def _generate_content_prompts(self, meta, chapters):
            """生成连续段落内容请求"""
            samples = []
            for chapter_num, title, content in chapters:
                paragraphs = self._split_paragraphs(content)
                outline = self._extract_summary(content)[:50]

                context_buffer = []
                for para_idx, para in enumerate(paragraphs):
                    # 构建上下文
                    if para_idx > 0:
                        context = " ".join([
                            f"第{p}段落：{paragraphs[p][-50:]}"
                            for p in range(max(0, para_idx-self.config['context_paragraphs']), para_idx)
                        ])
                    else:
                        context = "（开头）"

                    prompt = self.config['prompt_templates']['content_request'].format(
                        chapter=chapter_num,
                        outline=outline,
                        para_num=para_idx+1,
                        context=textwrap.shorten(context, 200, placeholder='...')
                    )

                    samples.append(self._build_dialogue_pair(prompt, para))

                    # 更新上下文缓冲区
                    context_buffer.append(para[-100:])  # 保留最后100字符作为下文
                    if len(context_buffer) > self.config['context_paragraphs']:
                        context_buffer.pop(0)
            return samples
    def process_folder(self):
            all_samples = []
            txt_files = list(self.input_dir.glob("*.txt"))
            for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
                all_samples.extend(self._process_single_file(file_path))
            return all_samples
    def run(self):
        self.output_dir.mkdir(exist_ok=True, parents=True)
        output_file = self.output_dir / f"{self.genre}_datasetSft.jsonl"

        samples = []
        txt_files = list(self.input_dir.glob("*.txt"))
        for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
            samples.extend(self._process_single_file(file_path))

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
