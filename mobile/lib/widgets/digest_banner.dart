import 'package:flutter/material.dart';

class DigestBanner extends StatelessWidget {
  final String text;
  const DigestBanner({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: scheme.primaryContainer.withOpacity(0.35),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.primary.withOpacity(0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.edit_note_outlined, size: 18, color: scheme.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurface.withOpacity(0.8),
                    height: 1.55,
                    fontStyle: FontStyle.italic,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}
