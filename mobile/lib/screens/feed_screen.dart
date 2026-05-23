import 'package:flutter/material.dart';
import '../models/article.dart';
import '../services/news_service.dart';
import '../widgets/article_card.dart';
import '../widgets/region_tab_bar.dart';
import '../widgets/digest_banner.dart';
import 'article_screen.dart';

class FeedScreen extends StatefulWidget {
  final VoidCallback onToggleTheme;
  final ThemeMode themeMode;

  const FeedScreen({
    super.key,
    required this.onToggleTheme,
    required this.themeMode,
  });

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends State<FeedScreen> {
  Newsletter? _newsletter;
  bool _loading = true;
  String? _error;
  String _selectedRegion = 'All';
  String _language = 'en';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool forceRefresh = false}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Show cached data immediately, then fetch fresh in background
      if (!forceRefresh) {
        final cached = await NewsService.instance.getCached();
        if (cached != null && mounted) {
          setState(() {
            _newsletter = cached;
            _loading = false;
          });
        }
      }
      final fresh = await NewsService.instance.fetchNewsletter(
        forceRefresh: forceRefresh,
      );
      if (mounted) {
        setState(() {
          _newsletter = fresh;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = _newsletter == null ? e.toString() : null;
          _loading = false;
        });
      }
    }
  }

  List<Article> get _articles {
    if (_newsletter == null) return [];
    return _newsletter!.articles.where((a) {
      if (a.language != _language) return false;
      if (_selectedRegion == 'All') return true;
      return a.region == _selectedRegion;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      appBar: _buildAppBar(isDark),
      body: RefreshIndicator(
        onRefresh: () => _load(forceRefresh: true),
        child: _buildBody(),
      ),
    );
  }

  AppBar _buildAppBar(bool isDark) {
    return AppBar(
      titleSpacing: 16,
      title: Row(
        children: [
          Text(
            'GeoPulse',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.5,
                ),
          ),
          if (_newsletter != null) ...[
            const SizedBox(width: 8),
            Text(
              _newsletter!.relativeAge,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context)
                        .colorScheme
                        .onSurface
                        .withOpacity(0.4),
                  ),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () =>
              setState(() => _language = _language == 'en' ? 'hi' : 'en'),
          child: Text(
            _language == 'en' ? 'हिंदी' : 'EN',
            style: TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 13,
              color: Theme.of(context).colorScheme.primary,
            ),
          ),
        ),
        IconButton(
          onPressed: widget.onToggleTheme,
          icon: Icon(
            isDark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
          ),
          tooltip: 'Toggle theme',
        ),
        const SizedBox(width: 4),
      ],
    );
  }

  Widget _buildBody() {
    // Full-screen error only when we have no data at all
    if (_error != null && _newsletter == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.cloud_off_outlined,
                size: 52,
                color: Theme.of(context).colorScheme.outline,
              ),
              const SizedBox(height: 16),
              Text(
                'Could not load news',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                'Check your connection and pull down to retry.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context)
                          .colorScheme
                          .onSurface
                          .withOpacity(0.55),
                    ),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: _load,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('Try again'),
              ),
            ],
          ),
        ),
      );
    }

    if (_loading && _newsletter == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final articles = _articles;
    final digest =
        _newsletter?.digest[_language] ?? _newsletter?.digest['en'] ?? '';

    return CustomScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      slivers: [
        SliverToBoxAdapter(
          child: RegionTabBar(
            selected: _selectedRegion,
            onSelected: (r) => setState(() => _selectedRegion = r),
          ),
        ),
        if (digest.isNotEmpty)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
              child: DigestBanner(text: digest),
            ),
          ),
        if (articles.isEmpty && !_loading)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Text(
                  'No stories in this region right now.',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Theme.of(context)
                            .colorScheme
                            .onSurface
                            .withOpacity(0.5),
                      ),
                ),
              ),
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 32),
            sliver: SliverList.builder(
              itemCount: articles.length,
              itemBuilder: (ctx, i) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: ArticleCard(
                  article: articles[i],
                  language: _language,
                  onTap: () => Navigator.push(
                    ctx,
                    MaterialPageRoute(
                      builder: (_) => ArticleScreen(
                        article: articles[i],
                        language: _language,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
