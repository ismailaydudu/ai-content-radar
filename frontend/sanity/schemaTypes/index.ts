import { type SchemaTypeDefinition } from 'sanity'
import movie from './movie'

export const schema: { types: SchemaTypeDefinition[] } = {
  types: [movie],
}
