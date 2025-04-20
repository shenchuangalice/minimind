import os
import json
import re
from tqdm import tqdm
import chardet
from pathlib import Path
import random
from faker import Faker

class NovelDialogueGenerator:
    def __init__(self, input_dir, output_dir):
        self.fake = Faker(locale='zh_CN')
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.genre = self.input_dir.name
        self.config = {
            'min_chunk': 800,
            'max_chunk': 2000,
            'title_pattern': r'^《(.+?)》|^【(.+?)】',
            'author_pattern': r'作者[：:]\s*([^\n]+?)(?:\n|$)',
            'volume_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+卷\s*.*?)\n',
            'chapter_pattern': r'(?:\n|^)(第[0-9一二三四五六七八九十百千万零]+[章回][^\n]*)(?:\n|$)',
            'outline_start': r'(?:内容简介|作品大纲)[：:\n]',
            'continuation_ratio': 0.35,
            'element_tags': {
                'character': ['主角', '配角', '反派', '导师'],
                'transition': ['三年后', '与此同时', '次日清晨', '转眼间']
            },
            'prompt_templates': [
                "请根据以下设定生成小说内容：\n类型：{genre}\n大纲：{outline}\n当前章节：第{chapter}章 {chapter_title}\n主要人物：{characters}",
                "请续写以下小说内容：\n类型：{genre}\n当前进度：{chapter_title}\n上下文：{context}",
                "根据以下元素生成章节内容：\n转场方式：{transitions}\n角色设定：{characters}",
                "请完善这个章节的细节描写：\n基本框架：{content}"
            ]
        }

    def detect_encoding(self, file_path):
        with open(file_path, 'rb') as f:
            raw = f.read()
            return chardet.detect(raw)['encoding'] if chardet.detect(raw)['confidence'] > 0.75 else 'utf-8'

    def _generate_elements(self):
        return {
            'characters': [f"{self.fake.name()}（{random.choice(self.config['element_tags']['character'])}）"
                          for _ in range(3)],
            'transitions': random.sample(self.config['element_tags']['transition'], 2)
        }

    def _build_dialogue_pair(self, prompt, content):
        return {
            "text": f"<s>{prompt}</s> <s>{content}</s>"
        }

    def _get_template_params(self, template):
        return set(re.findall(r'{(\w+)}', template))

    def _process_chapter(self, meta, content, elements):
        samples = []
        params_pool = {
            'genre': meta['genre'],
            'outline': (meta['outline'][:500] if meta['outline'] else "暂无大纲"),
            'chapter': meta['chapter'],
            'chapter_title': meta['chapter_title'],
            'characters': "、".join(elements['characters']),
            'transitions': "、".join(elements['transitions']),
            'content': content[:300],
            'context': ""
        }

        # 完整章节生成
        template = random.choice(self.config['prompt_templates'][:3])
        required_params = self._get_template_params(template)
        selected_params = {k: params_pool[k] for k in required_params}
        try:
            prompt = template.format(**selected_params)
            samples.append(self._build_dialogue_pair(prompt, content))
        except KeyError as e:
            print(f"模板参数缺失: {str(e)}")

        # 上下文续写
        if len(content) > 1000 and random.random() < 0.4:
            split_point = random.randint(500, len(content)-500)
            context = content[:split_point]
            continuation = content[split_point:]
            template = self.config['prompt_templates'][1]
            required_params = self._get_template_params(template)
            selected_params = {
                'genre': meta['genre'],
                'chapter_title': meta['chapter_title'],
                'context': context[-500:]
            }
            try:
                prompt = template.format(**selected_params)
                samples.append(self._build_dialogue_pair(prompt, continuation))
            except KeyError as e:
                print(f"续写模板参数缺失: {str(e)}")

        # 细节完善
        if random.random() < 0.2:
            key_sentence = "\n".join(content.split("\n")[::3])
            template = self.config['prompt_templates'][3]
            required_params = self._get_template_params(template)
            selected_params = {'content': key_sentence[:300]}
            try:
                prompt = template.format(**selected_params)
                samples.append(self._build_dialogue_pair(prompt, content))
            except KeyError as e:
                print(f"细节模板参数缺失: {str(e)}")

        return samples

    def _process_single_file(self, file_path):
        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                text = f.read().replace('\ufeff', '')

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
                    "chapter_title": ""
                }

                chapters = []
                last_pos = 0
                for match in re.finditer(self.config['chapter_pattern'], text):
                    chapter_title = match.group(1).strip()
                    start_pos = match.start()
                    if start_pos > last_pos:
                        chapters.append(('', text[last_pos:start_pos]))
                    chapters.append((chapter_title, ''))
                    last_pos = match.end()
                if last_pos < len(text):
                    chapters.append(('', text[last_pos:]))

                samples = []
                chapter_counter = 0
                current_content = []

                for title, content in chapters:
                    if title:
                        if chapter_counter > 0:
                            full_content = '\n'.join(current_content).strip()
                            if full_content:
                                meta["chapter"] = chapter_counter
                                meta["chapter_title"] = current_title
                                elements = self._generate_elements()
                                samples.extend(self._process_chapter(meta.copy(), full_content, elements))
                        chapter_counter += 1
                        current_title = title
                        current_content = [content]
                    else:
                        current_content.append(content)

                if current_content:
                    full_content = '\n'.join(current_content).strip()
                    if full_content:
                        meta["chapter"] = chapter_counter
                        meta["chapter_title"] = current_title
                        elements = self._generate_elements()
                        samples.extend(self._process_chapter(meta.copy(), full_content, elements))

                return samples
        except Exception as e:
            print(f"处理失败 {file_path}: {str(e)}")
            return []

    def process_folder(self):
        all_samples = []
        txt_files = list(self.input_dir.glob("*.txt"))
        for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
            all_samples.extend(self._process_single_file(file_path))
        return all_samples

    def run(self):
        self.output_dir.mkdir(exist_ok=True, parents=True)
        output_file = self.output_dir / f"{self.genre}_dialog.jsonl"

        samples = self.process_folder()
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in tqdm(samples, desc=f"写入 {self.genre} 数据"):
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    input_base = "./raw_novels"
    output_dir = "./structured_dialog"

    genre_dirs = [d for d in Path(input_base).iterdir() if d.is_dir()]
    for genre_dir in tqdm(genre_dirs, desc="处理总进度"):
        processor = NovelDialogueGenerator(genre_dir, output_dir)
        processor.run()
