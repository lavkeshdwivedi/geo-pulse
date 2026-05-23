class Article {
  final String title;
  final String url;
  final String source;
  final String publishedAt;
  final String? imageUrl;
  final String summary;
  final String region;
  final String language;
  final Map<String, dynamic> translations;

  const Article({
    required this.title,
    required this.url,
    required this.source,
    required this.publishedAt,
    this.imageUrl,
    required this.summary,
    required this.region,
    required this.language,
    required this.translations,
  });

  factory Article.fromJson(Map<String, dynamic> json) {
    return Article(
      title: json['title'] as String? ?? '',
      url: json['url'] as String? ?? '',
      source: json['source'] as String? ?? '',
      publishedAt: json['published_at'] as String? ?? '',
      imageUrl: json['image_url'] as String?,
      summary: json['summary'] as String? ?? '',
      region: json['region'] as String? ?? 'World',
      language: json['language'] as String? ?? 'en',
      translations: json['translations'] as Map<String, dynamic>? ?? {},
    );
  }

  String translatedTitle(String lang) {
    if (lang == 'en') return title;
    final t = translations[lang] as Map<String, dynamic>?;
    return t?['title'] as String? ?? title;
  }

  String translatedSummary(String lang) {
    if (lang == 'en') return summary;
    final t = translations[lang] as Map<String, dynamic>?;
    return t?['summary'] as String? ?? summary;
  }

  String translatedRegion(String lang) {
    if (lang == 'en') return region;
    final t = translations[lang] as Map<String, dynamic>?;
    return t?['region'] as String? ?? region;
  }

  String get relativeTime {
    try {
      final dt = DateTime.parse(publishedAt).toUtc();
      final diff = DateTime.now().toUtc().difference(dt);
      if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
      if (diff.inHours < 24) return '${diff.inHours}h ago';
      return '${diff.inDays}d ago';
    } catch (_) {
      return '';
    }
  }
}

class Newsletter {
  final String generatedAt;
  final int articleCount;
  final Map<String, String> digest;
  final List<Article> articles;

  const Newsletter({
    required this.generatedAt,
    required this.articleCount,
    required this.digest,
    required this.articles,
  });

  factory Newsletter.fromJson(Map<String, dynamic> json) {
    final digestRaw = json['digest'] as Map<String, dynamic>? ?? {};
    return Newsletter(
      generatedAt: json['generated_at'] as String? ?? '',
      articleCount: json['article_count'] as int? ?? 0,
      digest: digestRaw.map((k, v) => MapEntry(k, v.toString())),
      articles: (json['articles'] as List<dynamic>? ?? [])
          .map((e) => Article.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  String get relativeAge {
    try {
      final dt = DateTime.parse(generatedAt).toUtc();
      final diff = DateTime.now().toUtc().difference(dt);
      if (diff.inMinutes < 60) return 'Updated ${diff.inMinutes}m ago';
      if (diff.inHours < 24) return 'Updated ${diff.inHours}h ago';
      return 'Updated ${diff.inDays}d ago';
    } catch (_) {
      return '';
    }
  }
}
