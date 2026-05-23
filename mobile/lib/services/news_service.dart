import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/article.dart';

const _kJsonUrl = 'https://pulse.lavkesh.com/newsletter.json';
const _kCacheKey = 'newsletter_json_v1';
const _kCacheTimeKey = 'newsletter_fetched_at_v1';
const _kStaleDuration = Duration(minutes: 30);

class NewsService {
  NewsService._();
  static final NewsService instance = NewsService._();

  Future<Newsletter> fetchNewsletter({bool forceRefresh = false}) async {
    final prefs = await SharedPreferences.getInstance();

    if (!forceRefresh) {
      final cached = prefs.getString(_kCacheKey);
      final fetchedAt = prefs.getString(_kCacheTimeKey);
      if (cached != null && fetchedAt != null) {
        final age = DateTime.now().difference(DateTime.parse(fetchedAt));
        if (age < _kStaleDuration) {
          return _decode(cached);
        }
      }
    }

    final response = await http
        .get(Uri.parse(_kJsonUrl), headers: {'Accept': 'application/json'})
        .timeout(const Duration(seconds: 15));

    if (response.statusCode != 200) {
      throw Exception('Server returned ${response.statusCode}');
    }

    final body = utf8.decode(response.bodyBytes);
    await prefs.setString(_kCacheKey, body);
    await prefs.setString(_kCacheTimeKey, DateTime.now().toIso8601String());
    return _decode(body);
  }

  Future<Newsletter?> getCached() async {
    final prefs = await SharedPreferences.getInstance();
    final cached = prefs.getString(_kCacheKey);
    if (cached == null) return null;
    return _decode(cached);
  }

  Newsletter _decode(String json) =>
      Newsletter.fromJson(jsonDecode(json) as Map<String, dynamic>);
}
