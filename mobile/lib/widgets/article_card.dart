import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import '../models/article.dart';
import 'region_tab_bar.dart' show regionColor;

class ArticleCard extends StatelessWidget {
  final Article article;
  final String language;
  final VoidCallback onTap;

  const ArticleCard({
    super.key,
    required this.article,
    required this.language,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final color = regionColor(article.region);
    final hasImage = article.imageUrl != null && article.imageUrl!.isNotEmpty;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (hasImage)
              CachedNetworkImage(
                imageUrl: article.imageUrl!,
                height: 176,
                width: double.infinity,
                fit: BoxFit.cover,
                placeholder: (_, __) => Container(
                  height: 176,
                  color: color.withOpacity(0.12),
                  child: Center(
                    child: Icon(Icons.public_outlined,
                        size: 36, color: color.withOpacity(0.35)),
                  ),
                ),
                errorWidget: (_, __, ___) => Container(
                  height: 80,
                  color: color.withOpacity(0.08),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      _RegionChip(label: article.translatedRegion(language), color: color),
                      const SizedBox(width: 8),
                      if (article.relativeTime.isNotEmpty)
                        Text(
                          article.relativeTime,
                          style: textTheme.labelSmall?.copyWith(
                            color: scheme.onSurface.withOpacity(0.45),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    article.translatedTitle(language),
                    style: textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                      height: 1.3,
                    ),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    article.translatedSummary(language),
                    style: textTheme.bodyMedium?.copyWith(
                      color: scheme.onSurface.withOpacity(0.72),
                      height: 1.5,
                    ),
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 10),
                  Text(
                    article.source,
                    style: textTheme.labelSmall?.copyWith(
                      color: scheme.onSurface.withOpacity(0.4),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RegionChip extends StatelessWidget {
  final String label;
  final Color color;
  const _RegionChip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}
