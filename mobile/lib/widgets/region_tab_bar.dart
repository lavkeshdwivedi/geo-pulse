import 'package:flutter/material.dart';

Color regionColor(String region) => switch (region) {
      'Middle East & Africa' => const Color(0xFFE07B39),
      'Asia-Pacific' => const Color(0xFF2E86C1),
      'Americas' => const Color(0xFF27AE60),
      'Europe & Russia' => const Color(0xFFB03A2E),
      'Global / Multilateral' => const Color(0xFF7D3C98),
      _ => const Color(0xFF707B7C),
    };

const allRegions = [
  'All',
  'Middle East & Africa',
  'Asia-Pacific',
  'Americas',
  'Europe & Russia',
  'Global / Multilateral',
];

class RegionTabBar extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelected;

  const RegionTabBar({
    super.key,
    required this.selected,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 46,
      child: ListView.builder(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        itemCount: allRegions.length,
        itemBuilder: (_, i) {
          final region = allRegions[i];
          final isSelected = region == selected;
          final color = region == 'All'
              ? Theme.of(context).colorScheme.primary
              : regionColor(region);
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => onSelected(region),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
                decoration: BoxDecoration(
                  color: isSelected ? color : color.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  region,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: isSelected ? Colors.white : color,
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
